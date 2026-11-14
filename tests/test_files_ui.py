"""Regression checks for Files tab navigation and context menu behavior."""

import os
import pathlib

REPO = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_files_page_registers_navigation_guard():
    app_source = _read("web/app.js")
    files_source = _read("web/modules/files.js")

    assert "beforePageLeave" in app_source
    assert "setBeforePageLeave" in app_source
    assert "setBeforePageLeave(async ({ from })" in files_source
    assert "if (from !== 'files') return true;" in files_source


def test_new_file_discard_and_context_menu_clamp_regressions():
    source = _read("web/modules/files.js")
    shared = _read("web/modules/ui_interactions.js")

    assert "createNewFile({ force: true })" in source
    assert "bindMenu(contextMenuEl" in source
    assert "document.body.appendChild(contextMenuEl)" in source
    assert "leftEdge + width - rect.width" in shared
    assert "topEdge + height - rect.height" in shared


def test_files_page_explains_manager_role_and_directory_affordance():
    source = _read("web/modules/files.js")

    assert "button.type = 'button';" in source
    assert "(entry.type === 'file' ? formatFileSize(entry.size) : 'open')" in source


def test_files_layout_uses_internal_scroll_contract():
    css = _read("web/style.css")

    assert "flex: 1;" in css
    assert ".files-layout {" in css
    assert 'grid-template-areas: "sidebar preview";' in css
    assert ".files-sidebar {" in css
    assert "min-height: 0;" in css
    assert "overflow: hidden;" in css
    assert ".files-list {" in css
    assert "overscroll-behavior: contain;" in css
    assert "grid-template-rows: minmax(0, 30%) minmax(0, 1fr);" in css
    assert 'max-height: none;' in css








def test_desktop_bridge_version_skew_fallback_chain():
    """An OLD packaged launcher (frontend updates via managed repo, launcher
    only on reinstall) must degrade honestly, never into a silently dead
    control: external links copy to clipboard with a toast, byte saves toast
    that saving is unavailable, and file opens keep the long-shipped
    open_file_with_default_app -> download_file_to_downloads -> window.open
    chain."""
    helper = _read("web/modules/ui_helpers.js")

    assert "export async function openExternalViaHostBridge(" in helper
    assert "api.open_external_url ? await api.open_external_url(target) : null" in helper
    assert "await openExternalViaHostBridge(url, { api, win, doc, toast });" in helper
    assert "'Link copied — open it in your browser.'" in helper
    assert "api.save_bytes_to_downloads(payload.name, payload.b64)" in helper
    assert "downloadBlobViaHostBridge(url, filename, { win, doc })" in helper
    assert '"Saving isn\'t available in the app — open in a browser."' in helper
    # Existing file-method chain stays intact for the interceptor to reuse.
    assert "api?.open_file_with_default_app" in helper
    assert "api?.download_file_to_downloads" in helper
    assert "window.open(browserUrl || url, '_blank', 'noopener');" in helper
    # Without ANY file bridge the interceptor degrades the file class to the
    # copy-link fallback instead of looping the helpers back into its own shim.
    assert "fileBridgeReady" in helper
    # Framed-wizard parity: the helpers resolve the bridge through the shared
    # resolver (the bridge lives on the PARENT window inside the overlay iframe).
    assert helper.count("shellBridgeApi(window)") == 2




def test_files_confirm_dialog_results_are_normalized():
    source = _read("web/modules/files.js")
    helper = _read("web/modules/ui_helpers.js")
    primitives = _read("web/modules/ui_primitives.js")
    toast = _read("web/modules/toast.js")

    assert "typeof result === 'boolean' ? { confirmed: result, value: '' } : result" in source
    assert "return Boolean(result?.confirmed);" in source
    assert "if (!result?.confirmed) return;" in source
    assert "normalizeTone(tone || 'info', 'info')" in toast
    primitives = _read("web/modules/ui_primitives.js")
    assert "export function normalizeTone(tone = 'muted', fallback = 'muted')" in primitives
    assert "export { renderSafeField, collectSafeFieldValues, normalizeTone, setInlineStatus } from './ui_primitives.js';" in helper
