"""The Process Designer must stay a faithful view of the engine.

These build the real :class:`FlowsheetEditor` on Qt's off-screen platform and
drive it the way the inspector does: a variable edit has to re-run the engine,
reach the drawing and the KPI strip, and stay out of the case study until it is
applied. Each test names the failure it pins down.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

pytest.importorskip("PySide6", reason="the designer needs PySide6")
pytest.importorskip("matplotlib", reason="the main window embeds matplotlib")

from PySide6.QtWidgets import QApplication  # noqa: E402

from algametrix.templates import TEMPLATES, build_template  # noqa: E402
from desktop.flowsheet import builder as B  # noqa: E402
from desktop.flowsheet import process as P  # noqa: E402

POWDER = "Heterotrophic microalgae powder"
RACEWAY = TEMPLATES[0].name          # whole-biomass food case on a raceway


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from desktop.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


def _editor(window, template: str):
    """An editor wired to the window exactly as the designer tab wires it."""
    from desktop.flowsheet import FlowsheetEditor

    window.apply_scenario(build_template(template, window.lib))
    ed = FlowsheetEditor()
    ed.set_library(window.lib)
    ed.set_scenario_source(lambda: (window.build_scenario(), window.results))
    ed.set_scenario_sink(window.apply_scenario)
    assert ed.generate_from_scenario(confirm=False)
    return ed


def _var(ed, role: str, path: str) -> P.Variable:
    return next(v for v in P.variables_for(role, ed.session.scenario) if v.path == path)


def _node(ed, role: str):
    return next(n for n in ed.scene.flowsheet.nodes.values() if n.role == role)


def _plate_text(item) -> str:
    return " ".join(text for line in item._lines for _g, text in line)


@pytest.mark.parametrize("template", [t.name for t in TEMPLATES])
def test_every_template_draws_linked_and_annotated(window, template):
    # A block left without figures, or a KPI tile that disagrees with the
    # engine, would make the drawing look computed when it is not.
    ed = _editor(window, template)
    assert ed.session is not None and ed.session.results is not None
    for item in ed.scene.node_items.values():
        if item.node.role and item.node.role not in (B.EFFLUENT, B.VAPOUR, B.SPENT, "effluent:2"):
            assert item._lines, f"{item.node.tag} has no read-out"
        assert item._status in ("ok", "warning")
    # A feed can be empty (waste water covering the N and P, say); the process
    # line from the cultivation onwards never is.
    fs = ed.scene.flowsheet
    spine = (B.CULTIVATION, B.HARVEST, B.DRYING, B.DISRUPTION, B.EXTRACTION)
    for e in ed.scene.edge_items.values():
        src = fs.nodes[e.link.src_node]
        if P.role_base(src.role) in spine and e.link.src_port not in ("effluent", "vapour"):
            assert e.kind != "empty", f"{src.tag}.{e.link.src_port} carries nothing"
    expected = P.kpis(ed.session.results)
    for key, tile in ed.tiles.items():
        assert tile._value == pytest.approx(expected[key])


def test_a_variable_edit_reruns_the_engine_but_not_the_case(window):
    # The designer is a sandbox: the edit must move the drawing and the KPIs,
    # and the Scenario tab must not see it before "Apply".
    ed = _editor(window, RACEWAY)
    var = _var(ed, B.CULTIVATION, "system.productivity")
    before_cost = ed.tiles["cost"]._value
    plate_before = _plate_text(ed.scene.node_item(_node(ed, B.CULTIVATION).id))
    case_before = window.build_scenario().system.productivity

    ed._on_variable_edited(var, case_before * 1.5, True)

    assert ed.session.is_dirty
    assert ed.tiles["cost"]._value < before_cost
    assert _plate_text(ed.scene.node_item(_node(ed, B.CULTIVATION).id)) != plate_before
    assert window.build_scenario().system.productivity == case_before
    assert ed.btn_apply.isEnabled()
    assert ed.banner.isVisibleTo(ed)


def test_a_slider_drag_is_one_undo_step(window):
    # Thirty ticks of one drag must not take thirty undos to walk back.
    ed = _editor(window, RACEWAY)
    var = _var(ed, B.CULTIVATION, "system.productivity")
    x0 = P.get_value(ed.session.scenario, var.path)
    ed._on_variable_edited(var, x0 * 1.1, True)
    for k in range(2, 12):
        ed._on_variable_edited(var, x0 * (1 + 0.1 * k), False)
    assert len(ed.session.history) == 2
    ed.undo()
    assert P.get_value(ed.session.scenario, var.path) == pytest.approx(x0)
    assert not ed.session.is_dirty
    ed.redo()
    assert P.get_value(ed.session.scenario, var.path) == pytest.approx(x0 * 2.1)


def test_apply_hands_the_working_copy_to_the_case_study(window):
    ed = _editor(window, RACEWAY)
    var = _var(ed, B.HARVEST, "harvesting.recovery")
    ed._on_variable_edited(var, 0.9, True)
    designer_cost = ed.tiles["cost"]._value

    ed.apply_to_case()

    assert window.build_scenario().harvesting.recovery == pytest.approx(0.9)
    assert P.headline(window.results)[0] == pytest.approx(designer_cost)
    assert not ed.session.is_dirty
    assert ed.session.baseline.harvesting.recovery == pytest.approx(0.9)
    assert not ed.btn_apply.isEnabled()


def test_a_technology_swap_redraws_the_equipment_and_undo_restores_it(window):
    ed = _editor(window, POWDER)
    assert _node(ed, B.DRYING).kind == "spray_dryer"
    ed._on_technology(B.DRYING, "Drum drying")
    assert _node(ed, B.DRYING).kind == "drum_dryer"
    assert ed.session.scenario.drying.name == "Drum drying"
    ed._on_technology(B.HARVEST, "Centrifugation only")
    assert [n.kind for n in ed.scene.flowsheet.nodes.values() if n.role.startswith(B.HARVEST)] \
        == ["centrifuge"]
    ed.undo()
    ed.undo()
    assert _node(ed, B.DRYING).kind == "spray_dryer"
    assert sorted(n.role for n in ed.scene.flowsheet.nodes.values() if n.role.startswith(B.HARVEST)) \
        == ["harvest", "harvest:2"]


def test_an_inadmissible_point_is_flagged_on_its_block(window):
    # A refused input must not leave numbers on screen that look current.
    ed = _editor(window, RACEWAY)
    var = _var(ed, B.CULTIVATION, "system.productivity")
    ed.session.set_value(var, 0.0, coalesce=False)
    ed._session_changed(var.path)

    assert ed.session.results is None
    assert ed.scene.node_item(_node(ed, B.CULTIVATION).id)._status == "error"
    assert all(t._value is None for t in ed.tiles.values())
    assert "Not computed" in ed.banner_text.text()
    assert not ed.btn_apply.isEnabled()
    # the drawing keeps the last admissible point
    assert ed.scene.node_item(_node(ed, B.CULTIVATION).id)._lines
    ed.undo()
    assert ed.session.results is not None


def test_role_blocks_survive_delete_and_hand_drawn_ones_survive_a_swap(window):
    ed = _editor(window, POWDER)
    cult = _node(ed, B.CULTIVATION)
    ed.scene.select_node(cult.id)
    ed.scene.delete_selected()
    assert cult.id in ed.scene.flowsheet.nodes

    from PySide6.QtCore import QPointF

    ed.scene.add_node("pump", QPointF(600, 600))
    ed._on_technology(B.DRYING, "Drum drying")
    assert any(n.kind == "pump" and not n.role for n in ed.scene.flowsheet.nodes.values())


def test_the_designer_follows_a_case_changed_elsewhere(window):
    ed = _editor(window, RACEWAY)
    scn = window.build_scenario()
    scn.scale *= 2
    window.apply_scenario(scn)
    ed.maybe_autogenerate()
    assert ed.session.baseline.scale == pytest.approx(scn.scale)

    # with edits pending it asks instead of dropping them
    var = _var(ed, B.CULTIVATION, "system.productivity")
    ed._on_variable_edited(var, var.hi / 2, True)
    scn = window.build_scenario()
    scn.scale /= 2
    window.apply_scenario(scn)
    ed.maybe_autogenerate()
    assert ed.session.is_dirty
    assert "changed" in ed.banner_text.text()


def test_the_report_image_is_drawn_on_the_white_sheet(window, tmp_path):
    ed = _editor(window, POWDER)
    cult = _node(ed, B.CULTIVATION)
    ed.scene.select_node(cult.id)
    out = tmp_path / "pfd.png"
    assert ed.render_diagram_png(str(out))
    assert out.stat().st_size > 10_000
    from PySide6.QtGui import QImage

    corner = QImage(str(out)).pixelColor(4, 4)
    assert corner.lightness() > 200
    # the selection is only set aside for the picture
    assert ed.scene.node_item(cult.id).isSelected()


def test_every_layer_and_toggle_paints(window):
    ed = _editor(window, RACEWAY)
    ed.resize(1400, 900)
    for layer in ("none", "mass", "energy", "cost", "gwp"):
        ed.set_layer(layer)
        ed.grab()
    for key in ("areas", "utilities", "labels", "flow", "sheet", "map"):
        ed.toggle_btns[key].toggle()
        ed.grab()
    for idx in range(ed.dock.count()):
        ed.dock.setCurrentIndex(idx)
        ed.grab()
    assert ed.tornado.rows


def test_a_selected_block_shows_its_figures_at_once(window):
    # The page used to open without the block's figures and plant shares,
    # which only appeared after the next edit.
    ed = _editor(window, RACEWAY)
    ed.scene.select_node(_node(ed, B.HARVEST).id)
    assert ed.inspector.mode == ("linked", _node(ed, B.HARVEST).id)
    assert "No figures" not in ed.inspector._specs.text()
    assert ed.inspector._meters["annual_cost"].value_text
    assert ed.inspector._meters["power_kw"].share > 0


def test_fit_holds_until_the_user_zooms_and_the_map_stays_out_of_the_way(window, qapp):
    ed = _editor(window, RACEWAY)
    ed.resize(1400, 900)
    ed.show()

    def settle():
        for _ in range(4):
            qapp.processEvents()

    settle()
    ed.view.fit_content()
    k0 = ed.view.transform().m11()
    # the whole sheet is on screen, so the overview would only cover the title block
    assert not ed.view.minimap.isVisibleTo(ed.view)

    # a smaller window keeps the drawing fitted
    ed.resize(ed.width(), 700)
    settle()
    k_small = ed.view.transform().m11()
    assert k_small != pytest.approx(k0)
    ed.view.fit_content()
    assert ed.view.transform().m11() == pytest.approx(k_small)
    assert not ed.view.minimap.isVisibleTo(ed.view)

    # once zoomed by hand it stays where the user put it
    ed.view.zoom_by(2.0)
    k1 = ed.view.transform().m11()
    assert ed.view.minimap.isVisibleTo(ed.view)
    assert ed.btn_zoom.text() == f"{k1 * 100:.0f} %"
    ed.resize(ed.width(), 900)
    settle()
    assert ed.view.transform().m11() == pytest.approx(k1)

    ed.toggle_btns["map"].setChecked(False)
    assert not ed.view.minimap.isVisibleTo(ed.view)
    ed.close()


def test_a_long_case_name_does_not_widen_the_window(window):
    ed = _editor(window, RACEWAY)
    before = ed.minimumSizeHint().width()
    ed.pfd_subtitle.set_full_text("Linked to the case study:  " + "very long organism name " * 20)
    assert ed.minimumSizeHint().width() == before
    assert ed.pfd_subtitle.toolTip().startswith("Linked to the case study")
