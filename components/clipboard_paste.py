"""Clipboard image paste zone for Streamlit (Ctrl+V)."""
from __future__ import annotations

import streamlit.components.v1 as components


def clipboard_paste_zone(key: str = "clip") -> None:
    """Show a paste zone. User pastes image; we store base64 into session via text bridge.

    Streamlit cannot read clipboard natively. This zone uses a contenteditable div;
    after paste, user clicks 'Use pasted image' which reads from a companion text area
    filled by JS into an adjacent input mirrored via st.text_input with key.
    """
    components.html(
        f"""
<div id="paste-{key}" tabindex="0"
  style="border:2px dashed #94a3b8;border-radius:10px;padding:14px;min-height:72px;
         background:#f8fafc;color:#475569;font-family:system-ui,sans-serif;font-size:13px;
         outline:none;margin-bottom:6px;">
  Click here, then <b>Ctrl+V</b> / <b>Cmd+V</b> to paste a screenshot.
  <div id="prev-{key}" style="margin-top:8px;"></div>
</div>
<input type="hidden" id="b64-{key}" />
<script>
(() => {{
  const zone = document.getElementById("paste-{key}");
  const prev = document.getElementById("prev-{key}");
  const hidden = document.getElementById("b64-{key}");
  zone.addEventListener("paste", (e) => {{
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const it of items) {{
      if (it.type && it.type.indexOf("image") === 0) {{
        e.preventDefault();
        const file = it.getAsFile();
        const reader = new FileReader();
        reader.onload = (ev) => {{
          const dataUrl = ev.target.result;
          hidden.value = dataUrl;
          prev.innerHTML = '<img src="'+dataUrl+'" style="max-width:100%;max-height:160px;border-radius:8px;"/>';
          // Also push into parent Streamlit text inputs labeled bridge
          const labels = window.parent.document.querySelectorAll('label');
          for (const lab of labels) {{
            if ((lab.innerText || '').includes('clipboard_bridge_{key}')) {{
              const inp = lab.parentElement.querySelector('textarea, input');
              if (inp) {{
                const native = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype, 'value');
                // set via input event for Streamlit
                const el = lab.parentElement.querySelector('textarea') || lab.parentElement.querySelector('input');
                if (el) {{
                  el.value = dataUrl;
                  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                  el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
              }}
            }}
          }}
        }};
        reader.readAsDataURL(file);
        break;
      }}
    }}
  }});
}})();
</script>
        """,
        height=120,
    )
