"""Pack-scoped Add Content browser — the CurseForge-style in-pack content search.

Opened from Pack Detail's ADD CONTENT button instead of redirecting to the
global Discover page. The browsing context is bound to the pack being edited:
the Minecraft version and mod loader come from the pack (server-side filtered),
every result adds only to this pack, Install adds the latest compatible file,
and clicking a card opens the detail drawer where a specific version can be
picked. All search, pagination, retry, drawer and imagery behavior is inherited
unchanged from DiscoverView.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from common import icon_btn, label
from views.discover import VERSIONS, DiscoverView

_LOADER_LABEL = {"forge": "Forge", "fabric": "Fabric", "neoforge": "NeoForge", "quilt": "Quilt"}


class AddContentView(DiscoverView):
    back_requested = pyqtSignal()

    def __init__(self, api):
        super().__init__(api)
        self._pack: dict | None = None

        back = icon_btn(self.heading_row, "arrowleft", "Back to pack detail")
        back.clicked.connect(self.back_requested.emit)
        self._back_btn = back
        self._heading_col.insertWidget(0, back, 0)
        self._pack_line = label(self.heading_row, "", "mono muted")
        self._pack_line.setWordWrap(True)
        self._heading_col.addWidget(self._pack_line)

        # Mods only: this surface adds content to one pack. Modpack/shader/
        # world browsing stays on Discover.
        for type_id, control in self._type_btns.items():
            control.setVisible(type_id == "mod")
        self._type = "mod"

        # Version entries carry data values so a pack version outside the
        # global list can be selected without breaking index-based mapping.
        self._ver_box.blockSignals(True)
        while self._ver_box.count():
            self._ver_box.removeItem(0)
        self._ver_box.addItem("All MC versions", "auto")
        for version in VERSIONS[1:]:
            self._ver_box.addItem(version, version)
        self._ver_box.blockSignals(False)

    def set_builds(self, builds: list[dict]) -> None:
        pass  # scope binds to exactly one pack via set_pack; global refresh must not retarget

    def set_pack(self, build: dict) -> None:
        """Bind the browser to one pack and re-filter for its version/loader."""
        changed = (self._pack or {}).get("buildId") != build.get("buildId")
        self.builds = [build]
        self._target_id = build.get("buildId")
        self._pack = build

        name = build.get("name") or "pack"
        mc = str(build.get("mcVersion") or "")
        loader = str(build.get("loader") or "")
        self._heading_title.setText(f"Add content — {name}")
        self._heading_sub.setText(
            "Searches both catalogs live, pre-filtered to this pack's Minecraft version and loader.")
        self._pack_line.setText(
            f"{mc or '?'} · {_LOADER_LABEL.get(loader, (loader or '?').capitalize())} · every install targets this pack")

        label_text = _LOADER_LABEL.get(loader, "")
        idx = self._loader_box.findText(label_text) if label_text else -1
        self._loader_box.blockSignals(True)
        self._loader_box.setCurrentIndex(idx if idx >= 0 else 0)
        self._loader_box.blockSignals(False)
        from views.discover import LOADERS
        self._loader = loader if loader in LOADERS else "all"

        if mc and self._ver_box.findData(mc) < 0:
            self._ver_box.addItem(mc, mc)
        vidx = self._ver_box.findData(mc or "auto")
        self._ver_box.blockSignals(True)
        self._ver_box.setCurrentIndex(max(0, vidx))
        self._ver_box.blockSignals(False)
        self._version = mc or "auto"

        self._page = int(self._remembered.get(self._ctx_key(), 0) or 0)
        if changed or not self._hits:
            self._search_now()

    def _action(self, hit: dict) -> None:
        """Install adds the latest compatible version straight into this pack."""
        if not self._target_id:
            return
        self.add_mod.emit(self._target_id, hit.get("provider") or "modrinth",
                          hit.get("projectId") or hit.get("slug"), None, hit.get("projectType"))

    def _open_drawer(self, hit: dict) -> None:
        super()._open_drawer(hit)
        # The target pack is fixed by construction — hide the selector row.
        if getattr(self, "_target_box", None) is not None:
            self._target_box.hide()
        if getattr(self, "_target_label", None) is not None:
            self._target_label.hide()
