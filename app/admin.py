"""Admin panel web interface for AI Melody Bot."""

import logging
import subprocess
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


# ─── HTML Templates ───

def base_html(title: str, content: str, token: str) -> str:
    return f"""<!DOCTYPE html>
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
        @media (max-width: 768px) {{
            nav {{ padding: 12px 16px; gap: 12px; }}
            .container {{ padding: 16px 12px; }}
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); gap: 10px; }}
            .stat-card {{ padding: 16px; }}
            .stat-card .value {{ font-size: 24px; }}
            table {{ font-size: 13px; }}
            thead th, tbody td {{ padding: 8px 10px; }}
        }}
    </style>
    <script>
        function togglePrompt(el) {{
            el.classList.toggle('expanded');
        }}
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
</body>
</html>"""


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
        success_html = '<span class="success-msg">✅ Стартовые кредиты обновлены</span>'
    elif success == "model_set":
        success_html = f'<span class="success-msg">✅ Модель изменена на {config.suno_model}</span>'
    elif success == "daily_limit_set":
        success_html = f'<span class="success-msg">✅ Лимит изменён на {config.max_generations_per_user_per_day}/день</span>'

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
            <div class="label">Stars получено (из БД)</div>
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
                <td>🎁 Стартовые кредиты</td>
                <td>
                    <form method="POST" action="/admin/set_free_credits?{tp}" class="admin-form">
                        <input type="number" name="free_credits" value="{config.free_credits_on_signup}" min="0" max="100" class="admin-input">
                        <button type="submit" class="admin-btn">Сохранить</button>
                    </form>
                </td>
                <td>Кол-во бесплатных кредитов при первом /start</td>
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
        blocked = '<span class="badge badge-err">BAN</span>' if u["is_blocked"] else ""
        ref_badge = f'<span class="badge badge-info">{u["referral_count"]}👥</span>' if u.get("referral_count", 0) > 0 else ""
        rows += f"""<tr>
            <td><a class="link" href="/admin/user/{u['telegram_id']}?{tp}">{u['telegram_id']}</a></td>
            <td>{u.get('username') or '—'}</td>
            <td>{u.get('first_name') or '—'}</td>
            <td>{total_credits}🎵 {blocked}</td>
            <td>{u['gen_count']}</td>
            <td>⭐{u['total_stars']}</td>
            <td>{ref_badge}</td>
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
                <th>Рефералы</th>
                <th>Регистрация</th>
            </tr>
        </thead>
        <tbody>
            {rows if rows else '<tr><td colspan="8" class="empty">Нет пользователей</td></tr>'}
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

    # Get today's generation count
    today_count = await db.count_user_generations_today(telegram_id)

    gen_rows = ""
    for g in data["generations"]:
        status_class = "badge-ok" if g["status"] == "complete" else ("badge-err" if g["status"] == "error" else "badge-info")
        prompt_text = g.get("prompt") or ""
        prompt_short = (prompt_text[:80] + "...") if len(prompt_text) > 80 else prompt_text
        rating_display = f'⭐{g["rating"]}' if g.get("rating") else "—"
        gen_rows += f"""<tr>
            <td>{g['id']}</td>
            <td>{g.get('mode', '—')}</td>
            <td class="prompt-cell" onclick="togglePrompt(this)">
                <div class="prompt-short">{prompt_short}</div>
                <div class="prompt-full">{prompt_text}</div>
            </td>
            <td>{g.get('style', '—')}</td>
            <td>{g.get('voice_gender', '—')}</td>
            <td><span class="badge {status_class}">{g['status']}</span></td>
            <td>{rating_display}</td>
            <td>{g.get('credits_spent', 0)}🎵</td>
            <td>{fmt_date(g['created_at'])}</td>
        </tr>"""

    pay_rows = ""
    for p in data["payments"]:
        pay_rows += f"""<tr>
            <td>{p['id']}</td>
            <td>⭐{p['stars_amount']}</td>
            <td>{p['credits_purchased']}🎵</td>
            <td><span class="badge badge-ok">{p['status']}</span></td>
            <td><code>{p.get('tg_payment_id', '—')}</code></td>
            <td>{fmt_date(p['created_at'])}</td>
        </tr>"""

    content = f"""
    <div class="user-header">
        <div>
            <div class="name">{user.get('first_name', '—')} (@{user.get('username', '—')}){blocked_badge}</div>
            <div class="tgid">ID: {user['telegram_id']}</div>
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
                <th>Промпт (клик для раскрытия)</th>
                <th>Стиль</th>
                <th>Голос</th>
                <th>Статус</th>
                <th>Оценка</th>
                <th>Кредиты</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {gen_rows if gen_rows else '<tr><td colspan="9" class="empty">Нет генераций</td></tr>'}
        </tbody>
    </table>

    <div class="section-title">💰 Платежи ({len(data['payments'])})</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Stars</th>
                <th>Кредиты</th>
                <th>Статус</th>
                <th>Payment ID</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {pay_rows if pay_rows else '<tr><td colspan="6" class="empty">Нет платежей</td></tr>'}
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
        prompt_short = (prompt_text[:60] + "...") if len(prompt_text) > 60 else prompt_text
        user_label = f"@{g['username']}" if g.get("username") else str(g["user_id"])
        rating_display = f'⭐{g["rating"]}' if g.get("rating") else "—"
        rows += f"""<tr>
            <td>{g['id']}</td>
            <td><a class="link" href="/admin/user/{g['user_id']}?{tp}">{user_label}</a></td>
            <td>{g.get('mode', '—')}</td>
            <td class="prompt-cell" onclick="togglePrompt(this)">
                <div class="prompt-short">{prompt_short}</div>
                <div class="prompt-full">{prompt_text}</div>
            </td>
            <td>{g.get('style', '—')}</td>
            <td>{g.get('voice_gender', '—')}</td>
            <td><span class="badge {status_class}">{g['status']}</span></td>
            <td>{rating_display}</td>
            <td>{g.get('credits_spent', 0)}🎵</td>
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
                <th>Промпт (клик)</th>
                <th>Стиль</th>
                <th>Голос</th>
                <th>Статус</th>
                <th>Оценка</th>
                <th>Кредиты</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {rows if rows else '<tr><td colspan="10" class="empty">Нет генераций</td></tr>'}
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
        rows += f"""<tr>
            <td>{p['id']}</td>
            <td><a class="link" href="/admin/user/{p['user_id']}?{tp}">{user_label}</a></td>
            <td>⭐{p['stars_amount']}</td>
            <td>{p['credits_purchased']}🎵</td>
            <td><span class="badge badge-ok">{p['status']}</span></td>
            <td><code>{p.get('tg_payment_id', '—')}</code></td>
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
                <th>Stars</th>
                <th>Кредиты</th>
                <th>Статус</th>
                <th>Payment ID</th>
                <th>Дата</th>
            </tr>
        </thead>
        <tbody>
            {rows if rows else '<tr><td colspan="7" class="empty">Нет платежей</td></tr>'}
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
async def credit_user(request: web.Request):
    """Add credits to a user."""
    tp = token_param(request)
    telegram_id = int(request.match_info["id"])
    data = await request.post()
    try:
        amount = int(data.get("amount", 0))
        if 1 <= amount <= 1000:
            await db.update_user_credits(telegram_id, amount)
            logger.info(f"Admin credited {amount} to user {telegram_id}")
    except (ValueError, TypeError):
        amount = 0
    raise web.HTTPFound(f"/admin/user/{telegram_id}?{tp}&success=credited&amount={amount}")


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


# ─── App factory ───

def create_admin_app() -> web.Application:
    """Create the admin panel web application."""
    app = web.Application()
    app.router.add_get("/admin/", dashboard)
    app.router.add_post("/admin/set_model", set_model)
    app.router.add_post("/admin/set_free_credits", set_free_credits)
    app.router.add_post("/admin/set_daily_limit", set_daily_limit)
    app.router.add_get("/admin/users", users_list)
    app.router.add_get("/admin/user/{id}", user_detail)
    app.router.add_post("/admin/user/{id}/credit", credit_user)
    app.router.add_post("/admin/user/{id}/reset_counter", reset_daily_counter)
    app.router.add_get("/admin/generations", generations_list)
    app.router.add_get("/admin/payments", payments_list)
    return app
