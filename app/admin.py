"""Admin panel web interface for AI Melody Bot."""

import logging
import subprocess
import json
from datetime import datetime, timezone

from aiohttp import web

from app.config import config, persist_env_var
from app import database as db

logger = logging.getLogger(__name__)


# ─── Auth middleware ───

def check_token(request: web.Request) -> bool:
    """Check admin token from query params."""
    token = request.query.get("token", "")
    return token == config.admin_token and config.admin_token != ""


def auth_required(handler):
    """Decorator to require admin token."""
    async def wrapper(request: web.Request):
        if not check_token(request):
            return web.Response(
                text="<h1>403 Forbidden</h1><p>Invalid or missing admin token.</p>",
                content_type="text/html",
                status=403,
            )
        return await handler(request)
    return wrapper


def token_param(request: web.Request) -> str:
    """Get token query string for links."""
    return f"token={request.query.get('token', '')}"


def fmt_date(dt) -> str:
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y %H:%M")
    return str(dt)


MODE_LABELS = {
    "description": "💡 Идея",
    "lyrics": "✍️ Стихи",
    "greeting": "🎉 Поздравление",
    "stories": "📱 Сторис",
}


def _mode_label(g: dict) -> str:
    """Human-readable mode label from user_mode or mode."""
    mode = g.get("user_mode") or g.get("mode") or "description"
    return MODE_LABELS.get(mode, mode)


def _full_prompt(g: dict) -> str:
    """Extract full untruncated text from raw_input JSON, fallback to prompt."""
    raw = g.get("raw_input")
    if not raw:
        return g.get("prompt") or ""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return g.get("prompt") or ""
    # For description/lyrics mode: raw has {"text": ...}
    if "text" in data:
        return data["text"]
    # For greeting/stories: build readable summary from all fields
    parts = []
    for key, val in data.items():
        if val and key != "style_raw":
            parts.append(f"{key}: {val}")
    if data.get("style_raw"):
        parts.append(f"style: {data['style_raw']}")
    return "\n".join(parts) if parts else g.get("prompt") or ""


def _was_truncated(g: dict) -> bool:
    """Check if the user's input was truncated."""
    full = _full_prompt(g)
    prompt = g.get("prompt") or ""
    return len(full) > len(prompt)


def _build_modal_html(g: dict) -> str:
    """Build hidden data divs for the generation detail modal."""
    import html as html_mod
    # Sanitize strings from DB that may contain surrogate characters
    def _s(val):
        if not val:
            return ""
        if isinstance(val, str):
            return val.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
        return str(val)

    gen_lyrics = _s(g.get("generated_lyrics"))
    edited_lyrics = _s(g.get("edited_lyrics"))
    accented_lyrics = _s(g.get("accented_lyrics"))

    if not gen_lyrics:
        return "\u2014"

    lyrics_short = (gen_lyrics[:60] + "...") if len(gen_lyrics) > 60 else gen_lyrics

    # Build generation info fields
    mode_label = _mode_label(g)
    prompt_text = _s(g.get("prompt")) or "\u2014"
    style_text = _s(g.get("style")) or "\u2014"
    voice_text = _s(g.get("voice_gender")) or "\u2014"
    title_text = _s(g.get("generated_title")) or "\u2014"

    # Parse raw_input for original user inputs and GPT compression info
    raw_input_html = ""
    gpt_prompt_original = ""
    gpt_prompt_sent = ""
    was_gpt_compressed = False
    raw = g.get("raw_input")
    if raw:
        try:
            raw_data = json.loads(raw)
            # Extract GPT compression data
            gpt_prompt_original = raw_data.pop("lyrics_prompt_original", "")
            gpt_prompt_sent = raw_data.pop("lyrics_prompt_sent", "")
            was_gpt_compressed = raw_data.pop("gpt_compressed", False)

            raw_parts = []
            field_labels = {
                "text": "\u0422\u0435\u043a\u0441\u0442",
                "recipient": "\u041a\u043e\u043c\u0443",
                "name": "\u0418\u043c\u044f",
                "occasion": "\u041f\u043e\u0432\u043e\u0434",
                "mood": "\u041d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u0435",
                "details": "\u0414\u0435\u0442\u0430\u043b\u0438",
                "vibe": "\u0412\u0430\u0439\u0431",
                "context": "\u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442",
                "style_raw": "\u0421\u0442\u0438\u043b\u044c (\u043e\u0440\u0438\u0433\u0438\u043d\u0430\u043b)",
            }
            for key, val in raw_data.items():
                if val:
                    label = field_labels.get(key, key)
                    raw_parts.append(f'{label}: {html_mod.escape(str(val))}')
            if raw_parts:
                raw_input_html = '\\n'.join(raw_parts)
        except (json.JSONDecodeError, TypeError):
            pass

    # Hidden info divs
    info_html = (
        f'<div class="modal-info" data-key="\u0420\u0435\u0436\u0438\u043c" style="display:none">{html_mod.escape(mode_label)}</div>'
        f'<div class="modal-info" data-key="\u041f\u0440\u043e\u043c\u043f\u0442 (\u0441\u043e\u0431\u0440\u0430\u043d\u043d\u044b\u0439)" style="display:none">{html_mod.escape(prompt_text)}</div>'
        f'<div class="modal-info" data-key="\u0421\u0442\u0438\u043b\u044c" style="display:none">{html_mod.escape(style_text)}</div>'
        f'<div class="modal-info" data-key="\u0413\u043e\u043b\u043e\u0441" style="display:none">{html_mod.escape(voice_text)}</div>'
        f'<div class="modal-info" data-key="\u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a \u0418\u0418" style="display:none">{html_mod.escape(title_text)}</div>'
    )
    if raw_input_html:
        info_html += f'<div class="modal-info" data-key="\u0412\u0432\u043e\u0434 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f" style="display:none">{raw_input_html}</div>'
    if gpt_prompt_original:
        info_html += f'<div class="modal-info" data-key="\u041f\u0440\u043e\u043c\u043f\u0442 \u0434\u043b\u044f Lyrics API (\u0434\u043e)" style="display:none">{html_mod.escape(gpt_prompt_original)}</div>'
    if gpt_prompt_sent:
        label = "🤖 \u041f\u0440\u043e\u043c\u043f\u0442 \u0434\u043b\u044f Lyrics API (\u043f\u043e\u0441\u043b\u0435 GPT)" if was_gpt_compressed else "\u041f\u0440\u043e\u043c\u043f\u0442 \u0434\u043b\u044f Lyrics API"
        info_html += f'<div class="modal-info" data-key="{label}" style="display:none">{html_mod.escape(gpt_prompt_sent)}</div>'

    # Lyrics data divs
    lyrics_data = f'<div class="lyrics-data" data-label="📝 \u0421\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0439" data-class="" style="display:none">{html_mod.escape(gen_lyrics)}</div>'
    if edited_lyrics:
        lyrics_data += f'<div class="lyrics-data" data-label="✏️ \u041e\u0442\u0440\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0439" data-class="edited" style="display:none">{html_mod.escape(edited_lyrics)}</div>'
    if accented_lyrics:
        lyrics_data += f'<div class="lyrics-data" data-label="🔤 \u0421 \u0443\u0434\u0430\u0440\u0435\u043d\u0438\u044f\u043c\u0438" data-class="accented" style="display:none">{html_mod.escape(accented_lyrics)}</div>'

    return f'<button class="lyrics-cell-btn" onclick="openLyricsModal(this)">📝 {html_mod.escape(lyrics_short)}</button>{info_html}{lyrics_data}'


# ─── HTML Templates ───

def base_html(title: str, content: str, token: str) -> str:
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — AI Melody Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f23;
            color: #e0e0e0;
            min-height: 100vh;
        }}
        nav {{
            background: linear-gradient(135deg, #1a1a3e 0%, #2d1b69 100%);
            padding: 16px 32px;
            display: flex;
            align-items: center;
            gap: 32px;
            border-bottom: 1px solid rgba(139, 92, 246, 0.3);
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            flex-wrap: wrap;
        }}
        nav .logo {{
            font-size: 20px;
            font-weight: 700;
            color: #a78bfa;
            text-decoration: none;
        }}
        nav .logo:hover {{ color: #c4b5fd; }}
        nav a {{
            color: #94a3b8;
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            padding: 6px 14px;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        nav a:hover, nav a.active {{
            color: #e0e0e0;
            background: rgba(139, 92, 246, 0.2);
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 32px 24px;
        }}
        h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 24px;
            background: linear-gradient(135deg, #a78bfa, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background: linear-gradient(145deg, #1e1e3f 0%, #16162e 100%);
            border: 1px solid rgba(139, 92, 246, 0.15);
            border-radius: 16px;
            padding: 24px;
            text-align: center;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(139, 92, 246, 0.15);
        }}
        .stat-card .value {{
            font-size: 36px;
            font-weight: 700;
            color: #a78bfa;
            line-height: 1.2;
        }}
        .stat-card .label {{
            font-size: 13px;
            color: #6b7280;
            margin-top: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #16162e;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid rgba(139, 92, 246, 0.15);
        }}
        thead th {{
            background: linear-gradient(135deg, #1e1e3f, #252547);
            color: #a78bfa;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 14px 16px;
            text-align: left;
            white-space: nowrap;
        }}
        tbody td {{
            padding: 12px 16px;
            border-top: 1px solid rgba(139, 92, 246, 0.08);
            font-size: 14px;
            vertical-align: top;
        }}
        tbody tr:hover {{ background: rgba(139, 92, 246, 0.06); }}
        .badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }}
        .badge-ok {{ background: rgba(34, 197, 94, 0.15); color: #4ade80; }}
        .badge-warn {{ background: rgba(234, 179, 8, 0.15); color: #facc15; }}
        .badge-err {{ background: rgba(239, 68, 68, 0.15); color: #f87171; }}
        .badge-info {{ background: rgba(59, 130, 246, 0.15); color: #60a5fa; }}
        a.link {{ color: #818cf8; text-decoration: none; }}
        a.link:hover {{ text-decoration: underline; }}
        .prompt-cell {{
            max-width: 300px;
            cursor: pointer;
        }}
        .prompt-short {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 300px;
        }}
        .prompt-full {{
            display: none;
            white-space: pre-wrap;
            word-break: break-word;
            max-width: 500px;
            background: rgba(139, 92, 246, 0.08);
            padding: 8px 12px;
            border-radius: 8px;
            margin-top: 4px;
        }}
        .prompt-cell.expanded .prompt-short {{ display: none; }}
        .prompt-cell.expanded .prompt-full {{ display: block; }}
        .pagination {{
            display: flex;
            gap: 12px;
            margin-top: 20px;
            justify-content: center;
        }}
        .pagination a {{
            padding: 8px 18px;
            background: #1e1e3f;
            border: 1px solid rgba(139, 92, 246, 0.2);
            border-radius: 8px;
            color: #a78bfa;
            text-decoration: none;
            font-size: 14px;
            transition: all 0.2s;
        }}
        .pagination a:hover {{
            background: rgba(139, 92, 246, 0.2);
        }}
        .user-header {{
            display: flex;
            align-items: center;
            gap: 20px;
            margin-bottom: 28px;
            flex-wrap: wrap;
        }}
        .user-header .name {{
            font-size: 24px;
            font-weight: 700;
            color: #e0e0e0;
        }}
        .user-header .tgid {{
            font-size: 14px;
            color: #6b7280;
            font-family: monospace;
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 600;
            color: #818cf8;
            margin: 28px 0 14px;
        }}
        .empty {{ text-align: center; padding: 40px; color: #6b7280; }}
        .admin-form {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}
        .admin-input {{
            background: #1e1e3f;
            color: #e0e0e0;
            border: 1px solid rgba(139, 92, 246, 0.3);
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 14px;
            width: 80px;
        }}
        .admin-input:focus {{
            outline: none;
            border-color: #a78bfa;
        }}
        .admin-btn {{
            background: linear-gradient(135deg, #7c3aed, #6366f1);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 6px 16px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        .admin-btn:hover {{ opacity: 0.85; }}
        .admin-btn-green {{
            background: linear-gradient(135deg, #059669, #10b981);
        }}
        .success-msg {{
            display: inline-block;
            padding: 4px 12px;
            background: rgba(34, 197, 94, 0.15);
            color: #4ade80;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            margin-left: 8px;
        }}
        /* ─── Lyrics modal ─── */
        .lyrics-modal-overlay {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(6px);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }}
        .lyrics-modal-overlay.open {{ display: flex; }}
        .lyrics-modal {{
            background: linear-gradient(145deg, #1e1e3f 0%, #16162e 100%);
            border: 1px solid rgba(139, 92, 246, 0.3);
            border-radius: 16px;
            padding: 0;
            width: 90%;
            max-width: 700px;
            max-height: 85vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            animation: modalIn 0.2s ease-out;
        }}
        @keyframes modalIn {{
            from {{ transform: scale(0.95); opacity: 0; }}
            to {{ transform: scale(1); opacity: 1; }}
        }}
        .lyrics-modal-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 24px;
            border-bottom: 1px solid rgba(139, 92, 246, 0.15);
        }}
        .lyrics-modal-header h3 {{
            font-size: 18px;
            color: #a78bfa;
            font-weight: 700;
        }}
        .lyrics-modal-close {{
            background: none;
            border: none;
            color: #6b7280;
            font-size: 24px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .lyrics-modal-close:hover {{ color: #f87171; background: rgba(239,68,68,0.1); }}
        .lyrics-modal-body {{
            padding: 20px 24px;
            overflow-y: auto;
            flex: 1;
        }}
        .lyrics-section {{
            margin-bottom: 20px;
        }}
        .lyrics-section:last-child {{ margin-bottom: 0; }}
        .lyrics-section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
        }}
        .lyrics-section-title {{
            font-size: 14px;
            font-weight: 600;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .lyrics-copy-btn {{
            background: rgba(139, 92, 246, 0.15);
            border: 1px solid rgba(139, 92, 246, 0.3);
            color: #a78bfa;
            border-radius: 8px;
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .lyrics-copy-btn:hover {{ background: rgba(139, 92, 246, 0.3); }}
        .lyrics-copy-btn.copied {{
            background: rgba(34, 197, 94, 0.2);
            border-color: rgba(34, 197, 94, 0.4);
            color: #4ade80;
        }}
        .lyrics-text-block {{
            white-space: pre-wrap;
            word-break: break-word;
            background: rgba(0,0,0,0.25);
            padding: 14px 16px;
            border-radius: 10px;
            font-size: 14px;
            line-height: 1.6;
            border: 1px solid rgba(139, 92, 246, 0.08);
        }}
        .lyrics-text-block.edited {{ color: #facc15; }}
        .lyrics-text-block.accented {{ color: #4ade80; }}
        .lyrics-cell-btn {{
            background: none;
            border: none;
            color: inherit;
            cursor: pointer;
            text-align: left;
            padding: 0;
            font: inherit;
            width: 100%;
        }}
        .lyrics-cell-btn:hover {{ color: #a78bfa; }}
        .modal-info-grid {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 6px 12px;
            margin-bottom: 20px;
            padding: 14px 16px;
            background: rgba(0,0,0,0.25);
            border-radius: 10px;
            border: 1px solid rgba(139, 92, 246, 0.08);
            font-size: 13px;
        }}
        .modal-info-key {{
            color: #6b7280;
            font-weight: 600;
            white-space: nowrap;
        }}
        .modal-info-val {{
            color: #e0e0e0;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .modal-divider {{
            border: none;
            border-top: 1px solid rgba(139, 92, 246, 0.12);
            margin: 16px 0;
        }}
        @media (max-width: 768px) {{
            nav {{ padding: 12px 16px; gap: 12px; }}
            .container {{ padding: 16px 12px; }}
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); gap: 10px; }}
            .stat-card {{ padding: 16px; }}
            .stat-card .value {{ font-size: 24px; }}
            table {{ font-size: 13px; }}
            thead th, tbody td {{ padding: 8px 10px; }}
            .lyrics-modal {{ width: 95%; max-height: 90vh; }}
            .lyrics-modal-body {{ padding: 16px; }}
        }}
    </style>
    <script>
        function togglePrompt(el) {{
            el.classList.toggle('expanded');
        }}
        function openLyricsModal(el) {{
            var container = el.closest('td');
            var body = document.getElementById('lyricsModalBody');
            body.innerHTML = '';

            // Render info fields
            var infos = container.querySelectorAll('.modal-info');
            if (infos.length > 0) {{
                var grid = '<div class="modal-info-grid">';
                infos.forEach(function(info) {{
                    var key = info.getAttribute('data-key');
                    var val = info.textContent;
                    grid += '<div class="modal-info-key">' + key + '</div>';
                    grid += '<div class="modal-info-val">' + val.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
                }});
                grid += '</div>';
                body.insertAdjacentHTML('beforeend', grid);
            }}

            // Render lyrics sections
            var sections = container.querySelectorAll('.lyrics-data');
            sections.forEach(function(sec) {{
                var label = sec.getAttribute('data-label');
                var cls = sec.getAttribute('data-class') || '';
                var text = sec.textContent;
                var id = 'lyr_' + Math.random().toString(36).substr(2, 9);
                var html = '<div class="lyrics-section">' +
                    '<div class="lyrics-section-header">' +
                        '<span class="lyrics-section-title">' + label + '</span>' +
                        '<button class="lyrics-copy-btn" data-target="' + id + '" onclick="copyLyrics(this)">'+
                            '📋 Копировать</button>' +
                    '</div>' +
                    '<div class="lyrics-text-block ' + cls + '" id="' + id + '">' +
                        text.replace(/</g, '&lt;').replace(/>/g, '&gt;') +
                    '</div></div>';
                body.insertAdjacentHTML('beforeend', html);
            }});
            document.getElementById('lyricsModalOverlay').classList.add('open');
        }}
        function closeLyricsModal() {{
            document.getElementById('lyricsModalOverlay').classList.remove('open');
        }}
        function copyLyrics(btn) {{
            var id = btn.getAttribute('data-target');
            var el = document.getElementById(id);
            var text = el.textContent;
            navigator.clipboard.writeText(text).then(function() {{
                btn.innerHTML = '✅ Скопировано';
                btn.classList.add('copied');
                setTimeout(function() {{
                    btn.innerHTML = '📋 Копировать';
                    btn.classList.remove('copied');
                }}, 2000);
            }});
        }}
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') closeLyricsModal();
        }});
    </script>
</head>
<body>
    <nav>
        <a href="/admin/?{token}" class="logo">🎵 AI Melody</a>
        <a href="/admin/?{token}">📊 Дашборд</a>
        <a href="/admin/users?{token}">👥 Пользователи</a>
        <a href="/admin/generations?{token}">🎵 Генерации</a>
        <a href="/admin/payments?{token}">💰 Платежи</a>
    </nav>
    <div class="container">
        {content}
    </div>
    <!-- Lyrics modal -->
    <div class="lyrics-modal-overlay" id="lyricsModalOverlay" onclick="if(event.target===this)closeLyricsModal()">
        <div class="lyrics-modal">
            <div class="lyrics-modal-header">
                <h3>📝 Текст песни</h3>
                <button class="lyrics-modal-close" onclick="closeLyricsModal()">&times;</button>
            </div>
            <div class="lyrics-modal-body" id="lyricsModalBody"></div>
        </div>
    </div>
</body>
</html>"""
    # Sanitize any surrogate characters from DB data
    return html.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')


# ─── Handlers ───

@auth_required
async def dashboard(request: web.Request):
    stats = await db.admin_get_stats()
    tp = token_param(request)

    # Get Stars balance from Telegram Bot API
    stars_balance = "—"
    try:
        get_bot = request.app.get("get_bot")
        if get_bot:
            bot = get_bot()
            if bot:
                star_txns = await bot.get_star_transactions()
                # Calculate balance: sum of incoming - outgoing
                balance = 0
                for txn in star_txns.transactions:
                    if txn.source:  # incoming
                        balance += txn.amount
                    if txn.receiver:  # outgoing (refunds, withdrawals)
                        balance -= txn.amount
                stars_balance = str(balance)
    except Exception as e:
        logger.warning(f"Could not fetch Stars balance: {e}")
        stars_balance = "N/A"

    # Get last restart time
    last_restart = "—"
    try:
        get_start_time = request.app.get("get_start_time")
        if get_start_time:
            start_time = get_start_time()
            if start_time:
                # Convert UTC to Moscow time (UTC+3)
                import datetime as dt_mod
                msk_offset = dt_mod.timedelta(hours=3)
                msk_time = start_time + msk_offset
                last_restart = msk_time.strftime("%d.%m.%Y %H:%M:%S")
    except Exception as e:
        logger.warning(f"Could not get restart time: {e}")

    # Get last deploy time (from git commit date)
    last_deploy = "—"
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ci"],
            capture_output=True, text=True, timeout=5,
            cwd="/opt/telegram-suno-bot"
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse git date like "2026-02-21 16:04:00 +0300"
            git_date = datetime.strptime(result.stdout.strip(), "%Y-%m-%d %H:%M:%S %z")
            last_deploy = git_date.strftime("%d.%m.%Y %H:%M:%S")
    except FileNotFoundError:
        # Try current working directory as fallback
        try:
            import os
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ci"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            if result.returncode == 0 and result.stdout.strip():
                git_date = datetime.strptime(result.stdout.strip(), "%Y-%m-%d %H:%M:%S %z")
                last_deploy = git_date.strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Could not get deploy time: {e}")

    model = config.suno_model
    model_options = "".join(
        f'<option value="{m}" {"selected" if m == model else ""}>{m}</option>'
        for m in config.available_models
    )

    # Check for success messages
    success = request.query.get("success", "")
    success_html = ""
    if success == "credits_set":
        success_html = '<span class="success-msg">✅ Стартовые бесплатные обновлены</span>'
    elif success == "signup_credits_set":
        success_html = '<span class="success-msg">✅ Стартовые платные обновлены</span>'
    elif success == "model_set":
        success_html = f'<span class="success-msg">✅ Модель изменена на {config.suno_model}</span>'
    elif success == "daily_limit_set":
        success_html = f'<span class="success-msg">✅ Лимит изменён на {config.max_generations_per_user_per_day}/день</span>'
    elif success == "russian_prefix":
        status = "включен" if config.russian_language_prefix else "выключен"
        success_html = f'<span class="success-msg">✅ Префикс русского языка {status}</span>'
    elif success == "video_generation":
        status = "включена" if config.video_generation_enabled else "выключена"
        success_html = f'<span class="success-msg">✅ Генерация видео {status}</span>'
    elif success == "preview_settings":
        success_html = f'<span class="success-msg">✅ Настройки превью: старт {config.preview_start_percent}%, длительность {config.preview_duration_sec}сек</span>'
    elif success == "mass_credit":
        mc_amount = request.query.get("amount", "?")
        mc_total = request.query.get("total", "?")
        success_html = f'<span class="success-msg">✅ Начислено {mc_amount}🎵 для {mc_total} пользователей! Уведомления отправляются...</span>'

    content = f"""
    <h1>📊 Дашборд</h1>
    <div class="stats-grid">
        <div class="stat-card" style="border-color: rgba(234, 179, 8, 0.4); background: linear-gradient(145deg, #2a2204 0%, #16162e 100%);">
            <div class="value" style="color: #facc15;">⭐{stars_balance}</div>
            <div class="label">Баланс Stars (Telegram)</div>
        </div>
        <div class="stat-card">
            <div class="value">{stats['users_count']}</div>
            <div class="label">Пользователей</div>
        </div>
        <div class="stat-card">
            <div class="value">{stats['gens_count']}</div>
            <div class="label">Всего генераций</div>
        </div>
        <div class="stat-card">
            <div class="value">{stats['gens_complete']}</div>
            <div class="label">Успешных</div>
        </div>
        <div class="stat-card">
            <div class="value">{stats['gens_today']}</div>
            <div class="label">Сегодня</div>
        </div>
        <div class="stat-card">
            <div class="value">{stats['payments_count']}</div>
            <div class="label">Платежей</div>
        </div>
        <div class="stat-card">
            <div class="value">⭐{stats['total_stars']}</div>
            <div class="label">Stars получено</div>
        </div>
        <div class="stat-card" style="border-color: rgba(34, 197, 94, 0.4); background: linear-gradient(145deg, #0a2214 0%, #16162e 100%);">
            <div class="value" style="color: #4ade80;">{stats['total_rub']}₽</div>
            <div class="label">Рублей получено (карта)</div>
        </div>
        <div class="stat-card">
            <div class="value">{stats['total_credits_sold']}🎵</div>
            <div class="label">Кредитов продано</div>
        </div>
        <div class="stat-card">
            <div class="value" style="font-size: 22px;">⭐{stats['avg_rating']}</div>
            <div class="label">Средняя оценка</div>
        </div>
        <div class="stat-card" style="border-color: rgba(34, 197, 94, 0.4); background: linear-gradient(145deg, #0a2214 0%, #16162e 100%);">
            <div class="value" style="font-size: 18px; color: #4ade80;">🔄 {last_restart}</div>
            <div class="label">Последний перезапуск</div>
        </div>
        <div class="stat-card" style="border-color: rgba(59, 130, 246, 0.4); background: linear-gradient(145deg, #0a1628 0%, #16162e 100%);">
            <div class="value" style="font-size: 18px; color: #60a5fa;">🚀 {last_deploy}</div>
            <div class="label">Последний деплой</div>
        </div>
        <div class="stat-card" style="border-color: rgba(239, 68, 68, 0.4); background: linear-gradient(145deg, #2a0a0a 0%, #16162e 100%);">
            <div class="value" style="color: #f87171;">🚫 {stats['blocked_count']}</div>
            <div class="label">Заблокировали бота</div>
        </div>
    </div>

    <div class="section-title">⚙️ Конфигурация {success_html}</div>
    <table>
        <thead><tr><th>Параметр</th><th>Значение</th><th>Описание</th></tr></thead>
        <tbody>
            <tr><td>📡 API URL</td><td><code>{config.suno_api_url}</code> <span class="badge badge-info">SunoAPI.org</span></td><td>URL провайдера API</td></tr>
            <tr>
                <td>🤖 Модель генерации</td>
                <td>
                    <form method="POST" action="/admin/set_model?{tp}" class="admin-form">
                        <select name="model" class="admin-input" style="width:auto;">
                            {model_options}
                        </select>
                        <button type="submit" class="admin-btn">Применить</button>
                    </form>
                </td>
                <td>Версия модели Suno AI для генерации музыки</td>
            </tr>
            <tr>
                <td>🎁 Стартовые бесплатные (превью)</td>
                <td>
                    <form method="POST" action="/admin/set_free_credits?{tp}" class="admin-form">
                        <input type="number" name="free_credits" value="{config.free_credits_on_signup}" min="0" max="100" class="admin-input">
                        <button type="submit" class="admin-btn">Сохранить</button>
                    </form>
                </td>
                <td>Кол-во бесплатных кредитов (превью) при первом /start</td>
            </tr>
            <tr>
                <td>🎵 Стартовые платные</td>
                <td>
                    <form method="POST" action="/admin/set_signup_credits?{tp}" class="admin-form">
                        <input type="number" name="credits" value="{config.credits_on_signup}" min="0" max="100" class="admin-input">
                        <button type="submit" class="admin-btn">Сохранить</button>
                    </form>
                </td>
                <td>Кол-во платных кредитов (полные треки) при первом /start. По умолчанию 0</td>
            </tr>
            <tr>
                <td>📊 Лимит/день на юзера</td>
                <td>
                    <form method="POST" action="/admin/set_daily_limit?{tp}" class="admin-form">
                        <input type="number" name="daily_limit" value="{config.max_generations_per_user_per_day}" min="1" max="1000" class="admin-input">
                        <button type="submit" class="admin-btn">Сохранить</button>
                    </form>
                </td>
                <td>Максимум генераций в день на одного пользователя</td>
            </tr>
            <tr><td>📊 Лимит/час глобальный</td><td>{config.max_generations_per_hour}</td><td>Максимум генераций в час по всему боту (защита от перегрузки API)</td></tr>
            <tr>
                <td>🇷🇺 Песня на русском</td>
                <td>
                    <form method="POST" action="/admin/toggle_russian_prefix?{tp}" class="admin-form">
                        <span class="badge {'badge-ok' if config.russian_language_prefix else 'badge-warn'}">{'ВКЛ' if config.russian_language_prefix else 'ВЫКЛ'}</span>
                        <button type="submit" class="admin-btn">{"Выключить" if config.russian_language_prefix else "Включить"}</button>
                    </form>
                </td>
                <td>Добавляет "песня на русском языке" в начало описания для Suno API</td>
            </tr>
            <tr>
                <td>🎬 Генерация видео</td>
                <td>
                    <form method="POST" action="/admin/toggle_video_generation?{tp}" class="admin-form">
                        <span class="badge {'badge-ok' if config.video_generation_enabled else 'badge-warn'}">{'ВКЛ' if config.video_generation_enabled else 'ВЫКЛ'}</span>
                        <button type="submit" class="admin-btn">{"Выключить" if config.video_generation_enabled else "Включить"}</button>
                    </form>
                </td>
                <td>Генерирует MP4 видеоклип после создания аудио (доп. расход кредитов API)</td>
            </tr>
            <tr>
                <td>🎧 Превью трека</td>
                <td>
                    <form method="POST" action="/admin/set_preview_settings?{tp}" class="admin-form">
                        <label style="color:#6b7280;font-size:12px;">Старт %</label>
                        <input type="number" name="start_percent" value="{config.preview_start_percent}" min="0" max="90" class="admin-input" style="width:60px;">
                        <label style="color:#6b7280;font-size:12px;">Длит. сек</label>
                        <input type="number" name="duration_sec" value="{config.preview_duration_sec}" min="5" max="120" class="admin-input" style="width:60px;">
                        <button type="submit" class="admin-btn">Сохранить</button>
                    </form>
                </td>
                <td>Настройки превью для бесплатных генераций: откуда начинать (в % от трека) и сколько секунд</td>
            </tr>
        </tbody>
    </table>

    <div class="section-title">🛡️ Антифрод</div>
    <table>
        <thead><tr><th>Параметр</th><th>Значение</th><th>Описание</th></tr></thead>
        <tbody>
            <tr>
                <td>⏳ Возраст в боте</td>
                <td><span class="badge {'badge-warn' if config.min_account_age_hours > 0 else 'badge-ok'}">{config.min_account_age_hours}ч</span></td>
                <td>Сколько часов после /start нужно ждать чтобы использовать <b>бесплатные</b> кредиты. Защита от массовой регистрации ботов. <b>0 = выключено</b>. Покупка за Stars работает всегда.</td>
            </tr>
            <tr>
                <td>🆔 Мин. Telegram ID</td>
                <td><span class="badge {'badge-warn' if config.min_telegram_user_id > 0 else 'badge-ok'}">{config.min_telegram_user_id}</span></td>
                <td>Telegram ID растёт последовательно — чем выше ID, тем новее аккаунт. Если ID пользователя <b>выше</b> этого числа — бесплатные кредиты заблокированы (только покупка за Stars). <b>0 = выключено</b>.</td>
            </tr>
        </tbody>
    </table>

    <div class="section-title">🎁 Массовое начисление кредитов</div>
    <form method="POST" action="/admin/mass_credit_confirm?{tp}" class="admin-form" style="display:flex; gap:12px; flex-wrap:wrap; align-items:end;">
        <div>
            <label style="color:#6b7280;font-size:12px;">Кол-во 🎵 каждому</label>
            <input type="number" name="amount" min="1" max="100" value="1" class="admin-input" required style="width:80px;">
        </div>
        <div style="flex:1; min-width:200px;">
            <label style="color:#6b7280;font-size:12px;">Сообщение пользователям</label>
            <input type="text" name="message" placeholder="Напр. С 23 февраля! 🎉" class="admin-input" required style="width:100%;">
        </div>
        <button type="submit" class="admin-btn admin-btn-green">🎁 Начислить всем</button>
    </form>
    """
    return web.Response(
        text=base_html("Дашборд", content, tp),
        content_type="text/html",
    )


@auth_required
async def users_list(request: web.Request):
    page = int(request.query.get("page", "1"))
    per_page = 50
    offset = (page - 1) * per_page
    tp = token_param(request)

    users = await db.admin_get_users(limit=per_page, offset=offset)

    rows = ""
    for u in users:
        total_credits = u["credits"] + u["free_generations_left"]
        blocked = '<span class="badge badge-err">🚫 BAN</span>' if u["is_blocked"] else ""
        blocked_at_str = f' <span style="color:#6b7280;font-size:11px;">{fmt_date(u.get("blocked_at"))}</span>' if u["is_blocked"] and u.get("blocked_at") else ""
        ref_badge = f'<span class="badge badge-info">{u["referral_count"]}👥</span>' if u.get("referral_count", 0) > 0 else ""
        referred_src = f'<a class="link" href="/admin/user/{u["referred_by"]}?{tp}">👥 {u["referred_by"]}</a>' if u.get("referred_by") else "—"
        rows += f"""<tr>
            <td><a class="link" href="/admin/user/{u['telegram_id']}?{tp}">{u['telegram_id']}</a></td>
            <td>{u.get('username') or '—'}</td>
            <td>{u.get('first_name') or '—'}</td>
            <td>{total_credits}🎵 {blocked}{blocked_at_str}</td>
            <td>{u['gen_count']}</td>
            <td>⭐{u['total_stars']}</td>
            <td>{u.get('total_rub', 0)}₽</td>
            <td>{ref_badge}</td>
            <td>{referred_src}</td>
            <td>{fmt_date(u['created_at'])}</td>
        </tr>"""

    pagination = ""
    if page > 1:
        pagination += f'<a href="/admin/users?{tp}&page={page-1}">← Назад</a>'
    if len(users) == per_page:
        pagination += f'<a href="/admin/users?{tp}&page={page+1}">Вперёд →</a>'

    content = f"""
    <h1>👥 Пользователи</h1>
    <table>
        <thead>
            <tr>
                <th>Telegram ID</th>
                <th>Username</th>
                <th>Имя</th>
                <th>Баланс</th>
                <th>Генераций</th>
                <th>Stars</th>
                <th>Рубли</th>
                <th>Рефералы</th>
                <th>Источник</th>
                <th>Регистрация</th>
            </tr>
        </thead>
        <tbody>
            {rows if rows else '<tr><td colspan="10" class="empty">Нет пользователей</td></tr>'}
        </tbody>
    </table>
    <div class="pagination">{pagination}</div>
    """
    return web.Response(
        text=base_html("Пользователи", content, tp),
        content_type="text/html",
    )


@auth_required
async def user_detail(request: web.Request):
    telegram_id = int(request.match_info["id"])
    tp = token_param(request)

    data = await db.admin_get_user_detail(telegram_id)
    if not data:
        return web.Response(
            text=base_html("Не найден", '<div class="empty">Пользователь не найден</div>', tp),
            content_type="text/html",
            status=404,
        )

    user = data["user"]
    total_credits = user["credits"] + user["free_generations_left"]
    blocked_badge = ' <span class="badge badge-err">BLOCKED</span>' if user["is_blocked"] else ""

    # Check for success message
    success = request.query.get("success", "")
    success_html = ""
    if success == "credited":
        amount = request.query.get("amount", "")
        success_html = f'<span class="success-msg">✅ Начислено {amount}🎵</span>'
    elif success == "counter_reset":
        success_html = '<span class="success-msg">✅ Счётчик генераций сброшен</span>'
    elif success == "free_credited":
        amount = request.query.get("amount", "")
        success_html = f'<span class="success-msg">✅ Начислено {amount} бесплатных (превью)</span>'

    # Get today's generation count
    today_count = await db.count_user_generations_today(telegram_id)

    # Get balance transactions
    balance_txns = await db.admin_get_balance_transactions(telegram_id)

    gen_rows = ""
    for g in data["generations"]:
        status_class = "badge-ok" if g["status"] == "complete" else ("badge-err" if g["status"] == "error" else "badge-info")
        prompt_text = g.get("prompt") or ""
        prompt_short = (prompt_text[:60] + "...") if len(prompt_text) > 60 else prompt_text
        rating_display = f'⭐{g["rating"]}' if g.get("rating") else "—"
        error_text = g.get("error_message") or ""
        error_html = f'<div style="color:#f87171;font-size:12px;margin-top:4px;">❌ {error_text}</div>' if error_text else ""
        comment_text = g.get("user_comment") or ""
        comment_html = f'<div style="color:#60a5fa;font-size:12px;margin-top:4px;">💬 {comment_text[:100]}{"..." if len(comment_text) > 100 else ""}</div>' if comment_text else ""

        # Combined details modal button
        details_html = _build_modal_html(g)
        if details_html == "\u2014":
            details_html = f'<span style="color:#6b7280">{prompt_short or "\u2014"}</span>'

        gen_rows += f"""<tr>
            <td>{g['id']}</td>
            <td>{_mode_label(g)}</td>
            <td>{details_html}</td>
            <td>{g.get('style', '—')}</td>
            <td>{g.get('voice_gender', '—')}</td>
            <td><span class="badge {status_class}">{g['status']}</span>{error_html}</td>
            <td>{rating_display}</td>
            <td>{g.get('credits_spent', 0)}🎵</td>
            <td>{comment_html or '—'}</td>
            <td>{fmt_date(g['created_at'])}</td>
        </tr>"""

    pay_rows = ""
    for p in data["payments"]:
        ptype = p.get('payment_type', 'stars')
        if ptype == 'tbank':
            type_badge = '<span class="badge badge-ok">💳 Карта</span>'
            amount_display = f"{p.get('amount_rub', 0)}₽"
        else:
            type_badge = '<span class="badge badge-info">⭐ Stars</span>'
            amount_display = f"⭐{p['stars_amount']}"
        pay_rows += f"""<tr>
            <td>{p['id']}</td>
            <td>{type_badge}</td>
            <td>{amount_display}</td>
            <td>{p['credits_purchased']}🎵</td>
            <td><span class="badge badge-ok">{p['status']}</span></td>
            <td><code>{p.get('tg_payment_id') or p.get('tbank_payment_id') or '—'}</code></td>
            <td>{fmt_date(p['created_at'])}</td>
        </tr>"""

    # Build referred_by badge
    referred_by = user.get("referred_by")
    if referred_by:
        referred_html = f' <span class="badge badge-info" style="font-size:12px;">👥 от <a class="link" href="/admin/user/{referred_by}?{tp}" style="color:#60a5fa;">{referred_by}</a></span>'
    else:
        referred_html = ""

    content = f"""
    <div class="user-header">
        <div>
            <div class="name">{user.get('first_name', '—')} (@{user.get('username', '—')}){blocked_badge}</div>
            <div class="tgid">ID: {user['telegram_id']}{referred_html}</div>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="value">{total_credits}🎵</div>
            <div class="label">Баланс</div>
        </div>
        <div class="stat-card">
            <div class="value">{user['credits']}🎵</div>
            <div class="label">Оплаченные</div>
        </div>
        <div class="stat-card">
            <div class="value">{user['free_generations_left']}</div>
            <div class="label">Бесплатные</div>
        </div>
        <div class="stat-card">
            <div class="value">{user['content_violations']}/3</div>
            <div class="label">Нарушения</div>
        </div>
        <div class="stat-card">
            <div class="value">{data['referral_count']}👥</div>
            <div class="label">Рефералы</div>
        </div>
    </div>

    <div class="section-title">🔧 Действия {success_html}</div>
    <div style="display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 24px;">
        <form method="POST" action="/admin/user/{telegram_id}/credit?{tp}" class="admin-form">
            <input type="number" name="amount" placeholder="Кол-во" min="1" max="1000" class="admin-input" required>
            <button type="submit" class="admin-btn admin-btn-green">🎵 Начислить кредиты</button>
        </form>
        <form method="POST" action="/admin/user/{telegram_id}/credit_free?{tp}" class="admin-form">
            <input type="number" name="amount" placeholder="Кол-во" min="1" max="100" class="admin-input" required>
            <button type="submit" class="admin-btn" style="background: linear-gradient(135deg, #0891b2, #06b6d4);">🎁 Начислить бесплатные (превью)</button>
        </form>
        <form method="POST" action="/admin/user/{telegram_id}/reset_counter?{tp}" class="admin-form">
            <span style="color: #6b7280; font-size: 13px;">Сегодня: <b style="color:#a78bfa;">{today_count}/{config.max_generations_per_user_per_day}</b></span>
            <button type="submit" class="admin-btn" style="background: linear-gradient(135deg, #d97706, #f59e0b);">🔄 Сбросить счётчик</button>
        </form>
    </div>

    <div class="section-title">🎵 Генерации ({len(data['generations'])})</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Режим</th>
                <th>Детали</th>
                <th>Стиль</th>
                <th>Голос</th>
                <th>Статус</th>
                <th>Оценка</th>
                <th>Кредиты</th>
                <th>💬</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {gen_rows if gen_rows else '<tr><td colspan="10" class="empty">Нет генераций</td></tr>'}
        </tbody>
    </table>

    <div class="section-title">💰 Платежи ({len(data['payments'])})</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Тип</th>
                <th>Сумма</th>
                <th>Кредиты</th>
                <th>Статус</th>
                <th>Payment ID</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {pay_rows if pay_rows else '<tr><td colspan="7" class="empty">Нет платежей</td></tr>'}
        </tbody>
    </table>
    """

    # Build balance transactions section
    source_badges = {
        'stars': '<span class="badge badge-info">⭐ Stars</span>',
        'tbank': '<span class="badge badge-ok">💳 Карта</span>',
        'admin': '<span class="badge" style="background:rgba(139,92,246,0.15);color:#a78bfa;">👑 Админ</span>',
        'referral': '<span class="badge" style="background:rgba(236,72,153,0.15);color:#f472b6;">👥 Реферал</span>',
        'signup_bonus': '<span class="badge" style="background:rgba(34,197,94,0.15);color:#4ade80;">🎁 Бонус</span>',
        'generation': '<span class="badge" style="background:rgba(234,179,8,0.15);color:#facc15;">🎵 Генерация</span>',
        'download': '<span class="badge" style="background:rgba(59,130,246,0.15);color:#60a5fa;">⬇️ Скачивание</span>',
        'refund': '<span class="badge" style="background:rgba(239,68,68,0.15);color:#f87171;">↩️ Возврат</span>',
    }
    txn_rows = ""
    for t in balance_txns:
        badge = source_badges.get(t['source'], f'<span class="badge badge-info">{t["source"]}</span>')
        amount_str = f'+{t["amount"]}' if t['amount'] > 0 else str(t['amount'])
        amount_color = '#4ade80' if t['amount'] > 0 else '#f87171'
        txn_rows += f"""<tr>
            <td>{t['id']}</td>
            <td>{badge}</td>
            <td style="color: {amount_color}; font-weight: 600;">{amount_str}🎵</td>
            <td>{t.get('description') or '—'}</td>
            <td>{fmt_date(t['created_at'])}</td>
        </tr>"""

    content += f"""
    <div class="section-title">💳 История баланса ({len(balance_txns)})</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Источник</th>
                <th>Сумма</th>
                <th>Описание</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {txn_rows if txn_rows else '<tr><td colspan="5" class="empty">Нет записей</td></tr>'}
        </tbody>
    </table>
    """
    return web.Response(
        text=base_html(f"Пользователь {user.get('username', telegram_id)}", content, tp),
        content_type="text/html",
    )


@auth_required
async def generations_list(request: web.Request):
    page = int(request.query.get("page", "1"))
    per_page = 50
    offset = (page - 1) * per_page
    tp = token_param(request)

    gens = await db.admin_get_generations(limit=per_page, offset=offset)

    rows = ""
    for g in gens:
        status_class = "badge-ok" if g["status"] == "complete" else ("badge-err" if g["status"] == "error" else "badge-info")
        prompt_text = g.get("prompt") or ""
        prompt_short = (prompt_text[:50] + "...") if len(prompt_text) > 50 else prompt_text
        user_label = f"@{g['username']}" if g.get("username") else str(g["user_id"])
        rating_display = f'⭐{g["rating"]}' if g.get("rating") else "—"
        error_text = g.get("error_message") or ""
        error_html = f'<div style="color:#f87171;font-size:12px;margin-top:4px;">❌ {error_text}</div>' if error_text else ""
        comment_text = g.get("user_comment") or ""
        comment_html = f'<div style="color:#60a5fa;font-size:12px;margin-top:4px;">💬 {comment_text[:100]}{"..." if len(comment_text) > 100 else ""}</div>' if comment_text else ""

        # Combined details modal button
        details_html = _build_modal_html(g)
        if details_html == "\u2014":
            details_html = f'<span style="color:#6b7280">{prompt_short or "\u2014"}</span>'

        rows += f"""<tr>
            <td>{g['id']}</td>
            <td><a class="link" href="/admin/user/{g['user_id']}?{tp}">{user_label}</a></td>
            <td>{_mode_label(g)}</td>
            <td>{details_html}</td>
            <td>{g.get('style', '—')}</td>
            <td>{g.get('voice_gender', '—')}</td>
            <td><span class="badge {status_class}">{g['status']}</span>{error_html}</td>
            <td>{rating_display}</td>
            <td>{g.get('credits_spent', 0)}🎵</td>
            <td>{comment_html or '—'}</td>
            <td>{fmt_date(g['created_at'])}</td>
        </tr>"""

    pagination = ""
    if page > 1:
        pagination += f'<a href="/admin/generations?{tp}&page={page-1}">← Назад</a>'
    if len(gens) == per_page:
        pagination += f'<a href="/admin/generations?{tp}&page={page+1}">Вперёд →</a>'

    content = f"""
    <h1>🎵 Генерации</h1>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Пользователь</th>
                <th>Режим</th>
                <th>Детали</th>
                <th>Стиль</th>
                <th>Голос</th>
                <th>Статус</th>
                <th>Оценка</th>
                <th>Кредиты</th>
                <th>💬</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {rows if rows else '<tr><td colspan="11" class="empty">Нет генераций</td></tr>'}
        </tbody>
    </table>
    <div class="pagination">{pagination}</div>
    """
    return web.Response(
        text=base_html("Генерации", content, tp),
        content_type="text/html",
    )


@auth_required
async def payments_list(request: web.Request):
    page = int(request.query.get("page", "1"))
    per_page = 50
    offset = (page - 1) * per_page
    tp = token_param(request)

    payments = await db.admin_get_payments(limit=per_page, offset=offset)

    rows = ""
    for p in payments:
        user_label = f"@{p['username']}" if p.get("username") else str(p["user_id"])
        ptype = p.get('payment_type', 'stars')
        if ptype == 'tbank':
            type_badge = '<span class="badge badge-ok">💳 Карта</span>'
            amount_display = f"{p.get('amount_rub', 0)}₽"
        else:
            type_badge = '<span class="badge badge-info">⭐ Stars</span>'
            amount_display = f"⭐{p['stars_amount']}"
        status_class = 'badge-ok' if p['status'] == 'completed' else 'badge-warn'
        rows += f"""<tr>
            <td>{p['id']}</td>
            <td><a class="link" href="/admin/user/{p['user_id']}?{tp}">{user_label}</a></td>
            <td>{type_badge}</td>
            <td>{amount_display}</td>
            <td>{p['credits_purchased']}🎵</td>
            <td><span class="badge {status_class}">{p['status']}</span></td>
            <td><code>{p.get('tg_payment_id') or p.get('tbank_payment_id') or '—'}</code></td>
            <td>{fmt_date(p['created_at'])}</td>
        </tr>"""

    pagination = ""
    if page > 1:
        pagination += f'<a href="/admin/payments?{tp}&page={page-1}">← Назад</a>'
    if len(payments) == per_page:
        pagination += f'<a href="/admin/payments?{tp}&page={page+1}">Вперёд →</a>'

    content = f"""
    <h1>💰 Платежи</h1>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Пользователь</th>
                <th>Тип</th>
                <th>Сумма</th>
                <th>Кредиты</th>
                <th>Статус</th>
                <th>Payment ID</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {rows if rows else '<tr><td colspan="8" class="empty">Нет платежей</td></tr>'}
        </tbody>
    </table>
    <div class="pagination">{pagination}</div>
    """
    return web.Response(
        text=base_html("Платежи", content, tp),
        content_type="text/html",
    )


# ─── Admin actions ───

@auth_required
async def set_model(request: web.Request):
    """Change the Suno model at runtime."""
    tp = token_param(request)
    data = await request.post()
    new_model = data.get("model", "")
    if new_model in config.available_models:
        config.suno_model = new_model
        persist_env_var("SUNO_MODEL", new_model)
        # Reset suno client so it picks up any changes
        from app.suno_api import close_suno_client
        await close_suno_client()
        logger.info(f"Model changed to {new_model} via admin panel")
    raise web.HTTPFound(f"/admin/?{tp}&success=model_set")


@auth_required
async def set_free_credits(request: web.Request):
    """Change the number of free credits for new users."""
    tp = token_param(request)
    data = await request.post()
    try:
        new_value = int(data.get("free_credits", config.free_credits_on_signup))
        if 0 <= new_value <= 100:
            config.free_credits_on_signup = new_value
            persist_env_var("FREE_CREDITS_ON_SIGNUP", str(new_value))
            logger.info(f"Free credits on signup changed to {new_value} via admin panel")
    except (ValueError, TypeError):
        pass
    raise web.HTTPFound(f"/admin/?{tp}&success=credits_set")


@auth_required
async def set_signup_credits(request: web.Request):
    """Change the number of paid credits for new users."""
    tp = token_param(request)
    data = await request.post()
    try:
        new_value = int(data.get("credits", config.credits_on_signup))
        if 0 <= new_value <= 100:
            config.credits_on_signup = new_value
            persist_env_var("CREDITS_ON_SIGNUP", str(new_value))
            logger.info(f"Paid credits on signup changed to {new_value} via admin panel")
    except (ValueError, TypeError):
        pass
    raise web.HTTPFound(f"/admin/?{tp}&success=signup_credits_set")



@auth_required
async def credit_user(request: web.Request):
    """Add credits to a user."""
    tp = token_param(request)
    telegram_id = int(request.match_info["id"])
    data = await request.post()
    try:
        amount = int(data.get("amount", 0))
        if 1 <= amount <= 1000:
            await db.update_user_credits(telegram_id, amount)
            await db.log_balance_transaction(
                telegram_id, amount, 'admin', 'Начисление администратором',
            )
            logger.info(f"Admin credited {amount} to user {telegram_id}")
    except (ValueError, TypeError):
        amount = 0
    raise web.HTTPFound(f"/admin/user/{telegram_id}?{tp}&success=credited&amount={amount}")


@auth_required
async def credit_user_free(request: web.Request):
    """Add free (preview) credits to a user."""
    tp = token_param(request)
    telegram_id = int(request.match_info["id"])
    data = await request.post()
    try:
        amount = int(data.get("amount", 0))
        if 1 <= amount <= 100:
            await db.update_free_credits(telegram_id, amount)
            await db.log_balance_transaction(
                telegram_id, amount, 'admin', 'Бесплатные кредиты (превью) от админа',
            )
            logger.info(f"Admin gave {amount} free credits to user {telegram_id}")
    except (ValueError, TypeError):
        amount = 0
    raise web.HTTPFound(f"/admin/user/{telegram_id}?{tp}&success=free_credited&amount={amount}")


@auth_required
async def set_daily_limit(request: web.Request):
    """Change the daily generation limit per user."""
    tp = token_param(request)
    data = await request.post()
    try:
        new_value = int(data.get("daily_limit", config.max_generations_per_user_per_day))
        if 1 <= new_value <= 1000:
            config.max_generations_per_user_per_day = new_value
            persist_env_var("MAX_GENERATIONS_PER_USER_PER_DAY", str(new_value))
            logger.info(f"Daily generation limit changed to {new_value} via admin panel")
    except (ValueError, TypeError):
        pass
    raise web.HTTPFound(f"/admin/?{tp}&success=daily_limit_set")


@auth_required
async def reset_daily_counter(request: web.Request):
    """Reset the daily generation counter for a user by deleting today's generation records status."""
    tp = token_param(request)
    telegram_id = int(request.match_info["id"])
    await db.reset_user_daily_generations(telegram_id)
    logger.info(f"Admin reset daily generation counter for user {telegram_id}")
    raise web.HTTPFound(f"/admin/user/{telegram_id}?{tp}&success=counter_reset")


@auth_required
async def toggle_russian_prefix(request: web.Request):
    """Toggle the Russian language prefix for Suno prompts."""
    tp = token_param(request)
    new_value = not config.russian_language_prefix
    config.russian_language_prefix = new_value
    persist_env_var("RUSSIAN_LANGUAGE_PREFIX", "1" if new_value else "0")
    logger.info(f"Admin toggled russian_language_prefix to {new_value}")
    raise web.HTTPFound(f"/admin/?{tp}&success=russian_prefix")


@auth_required
async def toggle_video_generation(request: web.Request):
    """Toggle automatic video (MP4) generation after audio."""
    tp = token_param(request)
    new_value = not config.video_generation_enabled
    config.video_generation_enabled = new_value
    persist_env_var("VIDEO_GENERATION_ENABLED", "1" if new_value else "0")
    logger.info(f"Admin toggled video_generation_enabled to {new_value}")
    raise web.HTTPFound(f"/admin/?{tp}&success=video_generation")


@auth_required
async def set_preview_settings(request: web.Request):
    """Update preview start percent and duration."""
    tp = token_param(request)
    data = await request.post()
    start_pct = int(data.get("start_percent", config.preview_start_percent))
    dur_sec = int(data.get("duration_sec", config.preview_duration_sec))
    start_pct = max(0, min(90, start_pct))
    dur_sec = max(5, min(120, dur_sec))
    config.preview_start_percent = start_pct
    config.preview_duration_sec = dur_sec
    persist_env_var("PREVIEW_START_PERCENT", str(start_pct))
    persist_env_var("PREVIEW_DURATION_SEC", str(dur_sec))
    logger.info(f"Admin set preview: start={start_pct}%, duration={dur_sec}s")
    raise web.HTTPFound(f"/admin/?{tp}&success=preview_settings")


@auth_required
async def mass_credit_confirm(request: web.Request):
    """Show confirmation page before mass crediting all users."""
    tp = token_param(request)
    data = await request.post()
    amount = int(data.get("amount", 0))
    message_text = data.get("message", "").strip()

    if amount < 1 or amount > 100 or not message_text:
        raise web.HTTPFound(f"/admin/?{tp}")

    user_count = await db.admin_get_stats()
    total_users = user_count["users_count"]

    content = f"""
    <h1>🎁 Подтверждение массового начисления</h1>

    <div style="background: rgba(234,179,8,0.1); border: 1px solid rgba(234,179,8,0.3); border-radius: 8px; padding: 20px; margin: 20px 0;">
        <p style="color: #facc15; font-size: 18px; margin: 0 0 12px 0;">⚠️ Внимание!</p>
        <p>Вы собираетесь начислить <b style="color:#4ade80;">{amount}🎵</b> кредитов <b>каждому</b> из <b style="color:#60a5fa;">{total_users}</b> пользователей.</p>
        <p>Каждый пользователь получит уведомление:</p>
        <div style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 6px; margin: 8px 0;">
            🎵 Вам начислено <b>{amount}🎵</b>!<br><br>
            {message_text}
        </div>
    </div>

    <div style="display:flex; gap:16px;">
        <form method="POST" action="/admin/mass_credit_execute?{tp}">
            <input type="hidden" name="amount" value="{amount}">
            <input type="hidden" name="message" value="{message_text}">
            <button type="submit" class="admin-btn admin-btn-green" style="font-size:16px; padding: 12px 32px;">✅ Подтвердить и начислить</button>
        </form>
        <a href="/admin/?{tp}" class="admin-btn" style="display:inline-flex;align-items:center;text-decoration:none;padding:12px 32px;">❌ Отменить</a>
    </div>
    """
    return web.Response(
        text=base_html("Подтверждение начисления", content, tp),
        content_type="text/html",
    )


@auth_required
async def mass_credit_execute(request: web.Request):
    """Execute mass credit: add credits to all users and send notifications."""
    import asyncio
    tp = token_param(request)
    data = await request.post()
    amount = int(data.get("amount", 0))
    message_text = data.get("message", "").strip()

    if amount < 1 or amount > 100 or not message_text:
        raise web.HTTPFound(f"/admin/?{tp}")

    user_ids = await db.get_all_user_ids()
    total = len(user_ids)

    # Credit all users in DB
    credited = 0
    for uid in user_ids:
        try:
            await db.update_user_credits(uid, amount)
            await db.log_balance_transaction(
                uid, amount, 'admin', f'Массовое начисление: {message_text[:80]}',
            )
            credited += 1
        except Exception as e:
            logger.warning(f"Mass credit DB error for {uid}: {e}")

    logger.info(f"Mass credit: {credited}/{total} users got {amount} credits")

    # Send notifications in background
    get_bot = request.app.get("get_bot")
    if get_bot:
        bot = get_bot()
        notification_text = (
            f"🎵 <b>Вам начислено {amount}🎵!</b>\n\n"
            f"{message_text}"
        )

        async def _send_notifications():
            sent = 0
            blocked = 0
            failed = 0
            for uid in user_ids:
                try:
                    await bot.send_message(
                        chat_id=uid,
                        text=notification_text,
                        parse_mode="HTML",
                    )
                    sent += 1
                except Exception as e:
                    err = str(e).lower()
                    if "blocked" in err or "deactivated" in err or "not found" in err:
                        blocked += 1
                        await db.mark_user_blocked(uid)
                    else:
                        failed += 1
                await asyncio.sleep(0.04)
            logger.info(
                f"Mass credit notifications: sent={sent} blocked={blocked} failed={failed} total={total}"
            )

            # Send final report to admins
            report_text = (
                f"📢 <b>Массовое начисление завершено!</b>\n\n"
                f"🎵 Начислено: {amount}🎵 каждому\n"
                f"👥 Всего: {total}\n"
                f"✅ Доставлено: {sent}\n"
                f"🚫 Заблокировали бота: {blocked}\n"
                f"❌ Ошибки: {failed}"
            )
            from app.config import config as app_config
            for admin_id in app_config.admin_ids:
                try:
                    await bot.send_message(admin_id, report_text, parse_mode="HTML")
                except Exception:
                    pass

        asyncio.create_task(_send_notifications())

    raise web.HTTPFound(f"/admin/?{tp}&success=mass_credit&amount={amount}&total={total}")


# ─── App factory ───

def create_admin_app() -> web.Application:
    """Create the admin panel web application."""
    app = web.Application()
    app.router.add_get("/admin/", dashboard)
    app.router.add_post("/admin/set_model", set_model)
    app.router.add_post("/admin/set_free_credits", set_free_credits)
    app.router.add_post("/admin/set_signup_credits", set_signup_credits)
    app.router.add_post("/admin/set_daily_limit", set_daily_limit)
    app.router.add_post("/admin/toggle_russian_prefix", toggle_russian_prefix)
    app.router.add_post("/admin/toggle_video_generation", toggle_video_generation)
    app.router.add_post("/admin/set_preview_settings", set_preview_settings)
    app.router.add_get("/admin/users", users_list)
    app.router.add_get("/admin/user/{id}", user_detail)
    app.router.add_post("/admin/user/{id}/credit", credit_user)
    app.router.add_post("/admin/user/{id}/credit_free", credit_user_free)
    app.router.add_post("/admin/user/{id}/reset_counter", reset_daily_counter)
    app.router.add_get("/admin/generations", generations_list)
    app.router.add_get("/admin/payments", payments_list)
    app.router.add_post("/admin/mass_credit_confirm", mass_credit_confirm)
    app.router.add_post("/admin/mass_credit_execute", mass_credit_execute)
    return app
