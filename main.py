import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CONFIG_FILE = "config.json"
ITEMS_FILE = "items.json"
CARTS_FILE = "carts.json"
ORDERS_FILE = "orders.json"

DEFAULT_CONFIG = {
    "shop_channel_id": None,
    "checkout_channel_id": None,
    "orders_category_id": None,
    "delivery_role_id": None,
    "admin_role_id": None,
    "currency_name": "Аров",
    "shop_title": "🛒 Minecraft Shop",
    "shop_description": "Выбери предметы из списка ниже и добавь в корзину!",
    "order_prefix": "заказ"
}

# Шаблон предметов с поддержкой 'per_qty' (цена за пачку/стак) и 'stock' (склад)
DEFAULT_ITEMS = [
    {"id": "oak_log", "name": "Дубовое бревно", "emoji": "🪵", "price": 4, "per_qty": 64, "description": "Прочные дубовые бревна стаками", "stock": 320},
    {"id": "diamond", "name": "Алмаз", "emoji": "💎", "price": 50, "per_qty": 1, "description": "1x Алмаз", "stock": -1},
    {"id": "netherite", "name": "Незерит", "emoji": "⚫", "price": 200, "per_qty": 1, "description": "1x Незеритовый слиток", "stock": -1},
    {"id": "elytra", "name": "Элитры", "emoji": "🦋", "price": 1500, "per_qty": 1, "description": "1x Элитры", "stock": -1},
    {"id": "enchanted_book", "name": "Зачарованная книга", "emoji": "📖", "price": 300, "per_qty": 1, "description": "1x Книга (Fortune III)", "stock": -1},
    {"id": "shulker", "name": "Шалкеровый ящик", "emoji": "🟣", "price": 400, "per_qty": 1, "description": "1x Шалкеровый ящик", "stock": -1},
]

def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return default.copy() if isinstance(default, dict) else list(default)

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_config():
    return load_json(CONFIG_FILE, DEFAULT_CONFIG)

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

def get_items():
    return load_json(ITEMS_FILE, DEFAULT_ITEMS)

def save_items(items):
    save_json(ITEMS_FILE, items)

def get_carts():
    return load_json(CARTS_FILE, {})

def save_carts(carts):
    save_json(CARTS_FILE, carts)

def get_orders():
    return load_json(ORDERS_FILE, {})

def save_orders(orders):
    save_json(ORDERS_FILE, orders)

def cart_total(cart_items):
    """
    Калькулятор работает на основе количества заказанных комплектов/стаков (qty_units).
    Если бревна стоят 4 алмаза за стак, и заказано 4 стака, то итоговая стоимость: 4 * 4 = 16 алмазов.
    """
    items = get_items()
    item_map = {i["id"]: i for i in items}
    total = 0.0
    for item_id, qty_units in cart_items.items():
        if item_id in item_map:
            it = item_map[item_id]
            total += qty_units * it["price"]
    return round(total, 2)

def format_price(value):
    """Красиво убирает .0 если число целое, иначе оставляет 2 знака"""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"

def cart_summary(cart_items):
    items = get_items()
    item_map = {i["id"]: i for i in items}
    lines = []
    cfg = get_config()
    for item_id, qty_units in cart_items.items():
        if item_id in item_map:
            it = item_map[item_id]
            per_qty = it.get("per_qty", 1)
            total_items = round(qty_units * per_qty)
            cost = qty_units * it["price"]
            
            # Делим на стаки и штуки для красивого Minecraft-отображения
            packs = total_items // per_qty
            rem_items = total_items % per_qty
            
            unit_str = "компл." if per_qty > 1 else "шт."
            if per_qty == 64:
                unit_str = "стак."
                
            qty_parts = []
            if packs > 0:
                qty_parts.append(f"{packs} {unit_str}")
            if rem_items > 0 or not qty_parts:
                qty_parts.append(f"{rem_items} шт.")
                
            qty_display = " + ".join(qty_parts)
            
            lines.append(
                f"{it['emoji']} **{it['name']}** x{qty_display} ({total_items} шт.) — "
                f"{format_price(cost)} {cfg['currency_name']}"
            )
    return "\n".join(lines) if lines else "_Корзина пуста_"

def get_page_from_embed(message: discord.Message) -> int:
    try:
        if message.embeds:
            footer = message.embeds[0].footer.text
            if "Страница" in footer:
                part = footer.split("Страница ")[1].split("/")[0]
                return int(part) - 1
    except Exception:
        pass
    return 0

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ══════════════════════════════════════════════════════════════════════════════
# VIEWS (ИНТЕРФЕЙСЫ)
# ══════════════════════════════════════════════════════════════════════════════

class ShopView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=None)
        self.page = page
        
        self.add_item(ItemSelectMenu(page))
        self.add_item(ViewCartButton())
        self.add_item(ClearCartButton())
        
        items = get_items()
        total_pages = max(1, (len(items) - 1) // 8 + 1)
        
        if total_pages > 1:
            self.add_item(PrevPageButton(disabled=(page == 0)))
            self.add_item(NextPageButton(disabled=(page >= total_pages - 1)))

class PrevPageButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="◀️ Назад", 
            style=discord.ButtonStyle.primary, 
            custom_id="shop_prev_page", 
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        page = get_page_from_embed(interaction.message)
        next_page = max(0, page - 1)
        cfg = get_config()
        await interaction.response.defer()
        await update_shop_message(interaction.message, cfg, next_page)

class NextPageButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="Вперед ▶️", 
            style=discord.ButtonStyle.primary, 
            custom_id="shop_next_page", 
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        page = get_page_from_embed(interaction.message)
        items = get_items()
        total_pages = max(1, (len(items) - 1) // 8 + 1)
        next_page = min(total_pages - 1, page + 1)
        cfg = get_config()
        await interaction.response.defer()
        await update_shop_message(interaction.message, cfg, next_page)

class ItemSelectMenu(discord.ui.Select):
    def __init__(self, page: int = 0):
        items = get_items()
        options = []
        used_ids = set()

        start_idx = page * 8
        end_idx = start_idx + 8
        page_items = items[start_idx:end_idx]

        cfg = get_config()

        for it in page_items:
            if it["id"] in used_ids:
                continue
            
            stock = it.get("stock", -1)
            per_qty = it.get("per_qty", 1)
            
            # Рассчитываем доступный запас в стаках/комплектах
            if stock == -1:
                stock_str = "∞"
            else:
                stock_units = stock // per_qty
                stock_str = f"{stock_units} стак." if per_qty == 64 else f"{stock_units} компл."
                if stock_units == 0:
                    stock_str = "Закончился"

            price_suffix = f" за {per_qty} шт." if per_qty > 1 else ""

            options.append(
                discord.SelectOption(
                    label=f"{it['name']} — {it['price']} {cfg['currency_name']}{price_suffix}",
                    value=it["id"],
                    description=f"В наличии: {stock_str} | {it.get('description', '')}"[:100],
                    emoji=it.get("emoji", "🔹")
                )
            )
            used_ids.add(it["id"])

        if not options:
            options.append(discord.SelectOption(label="Нет товаров на этой странице", value="empty_page"))

        super().__init__(
            placeholder="🛒 Выбери предмет для добавления в корзину...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_item_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty_page":
            await interaction.response.send_message("❌ На этой странице нет доступных товаров!", ephemeral=True)
            return

        item_id = self.values[0]
        items = get_items()
        item_map = {i["id"]: i for i in items}
        it = item_map.get(item_id)

        if not it:
            await interaction.response.send_message("❌ Товар не найден в базе данных!", ephemeral=True)
            return

        await interaction.response.send_modal(AddToCartQuantityModal(it))

class AddToCartQuantityModal(discord.ui.Modal):
    def __init__(self, item):
        super().__init__(title=f"🛒 Количество: {item['name']}")
        self.item = item
        
        stock = item.get("stock", -1)
        per_qty = item.get("per_qty", 1)
        
        unit_name = "стаков" if per_qty == 64 else "комплектов"
        if per_qty == 1:
            unit_name = "штук"

        # Лимитируем остатки для подписей
        if stock == -1:
            stock_packs = "∞"
            stock_items = "∞"
        else:
            stock_packs = f"{stock // per_qty}"
            stock_items = f"{stock}"
        
        self.qty_packs = discord.ui.TextInput(
            label=f"В {unit_name} (Доступно: {stock_packs})",
            placeholder=f"Например: 2 (можно оставить пустым)",
            default="",
            min_length=0,
            max_length=8,
            required=False
        )
        self.qty_items = discord.ui.TextInput(
            label=f"В штуках (Доступно: {stock_items})",
            placeholder=f"Например: 128 (можно оставить пустым)",
            default="",
            min_length=0,
            max_length=8,
            required=False
        )
        
        # Если продажа идет поштучно (1 штука в пакете), показываем только ввод в штуках
        if per_qty > 1:
            self.add_item(self.qty_packs)
        self.add_item(self.qty_items)

    async def on_submit(self, interaction: discord.Interaction):
        per_qty = self.item.get("per_qty", 1)
        
        packs_val = self.qty_packs.value.strip() if hasattr(self, 'qty_packs') else ""
        items_val = self.qty_items.value.strip() if hasattr(self, 'qty_items') else ""

        if per_qty == 1:
            if not items_val:
                await interaction.response.send_message("❌ Пожалуйста, укажите количество штук!", ephemeral=True)
                return
            packs_val = ""

        if not packs_val and not items_val:
            await interaction.response.send_message("❌ Укажите количество хотя бы в одном из полей!", ephemeral=True)
            return

        qty_packs_int = 0
        qty_items_int = 0

        if packs_val:
            try:
                qty_packs_int = int(packs_val)
                if qty_packs_int < 0:
                    raise ValueError()
            except ValueError:
                await interaction.response.send_message("❌ В поле стаков/комплектов должно быть целое положительное число!", ephemeral=True)
                return

        if items_val:
            try:
                qty_items_int = int(items_val)
                if qty_items_int < 0:
                    raise ValueError()
            except ValueError:
                await interaction.response.send_message("❌ В поле штук должно быть целое положительное число!", ephemeral=True)
                return

        total_items_requested = (qty_packs_int * per_qty) + qty_items_int

        if total_items_requested <= 0:
            await interaction.response.send_message("❌ Количество должно быть больше нуля!", ephemeral=True)
            return

        added_qty_units = total_items_requested / per_qty

        carts = get_carts()
        uid = str(interaction.user.id)
        if uid not in carts:
            carts[uid] = {}

        item_id = self.item["id"]
        stock = self.item.get("stock", -1)
        
        current_qty_units = carts[uid].get(item_id, 0)
        new_total_units = current_qty_units + added_qty_units
        new_total_items = round(new_total_units * per_qty)

        # Проверка лимитов на складе
        if stock != -1 and new_total_items > stock:
            if stock == 0:
                await interaction.response.send_message("❌ К сожалению, этот товар закончился на складе!", ephemeral=True)
            else:
                current_items_in_cart = round(current_qty_units * per_qty)
                await interaction.response.send_message(
                    f"❌ Нельзя заказать такое количество! На складе доступно всего: `{stock} шт.`\n"
                    f"У вас в корзине уже: `{current_items_in_cart} шт.`. Вы пытаетесь добавить еще: `{total_items_requested} шт.`.", 
                    ephemeral=True
                )
            return

        carts[uid][item_id] = new_total_units
        save_carts(carts)

        cfg = get_config()
        tot_val = cart_total(carts[uid])
        
        # Красивая разбивка в сообщении о добавлении
        added_packs_display = total_items_requested // per_qty
        added_rem_items = total_items_requested % per_qty
        
        unit_str = "стак." if per_qty == 64 else "компл."
        if per_qty == 1:
            unit_str = "шт."

        parts = []
        if added_packs_display > 0:
            parts.append(f"{added_packs_display} {unit_str}")
        if added_rem_items > 0 or not parts:
            parts.append(f"{added_rem_items} шт.")
        
        qty_display_str = " + ".join(parts)

        embed = discord.Embed(
            title="✅ Добавлено в корзину!",
            description=f"{self.item.get('emoji','🔹')} **{self.item['name']}** +{qty_display_str} (всего добавлено {total_items_requested} шт.)\n\n"
                        f"Всего в корзине товаров на сумму **{format_price(tot_val)} {cfg['currency_name']}**",
            color=0x57F287
        )
        embed.set_footer(text="Перейди в канал оформления заказа когда будешь готов!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ViewCartButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🛒 Моя корзина", style=discord.ButtonStyle.secondary, custom_id="view_cart_btn")

    async def callback(self, interaction: discord.Interaction):
        carts = get_carts()
        uid = str(interaction.user.id)
        cart = carts.get(uid, {})
        cfg = get_config()

        embed = discord.Embed(title="🛒 Ваша корзина", color=0x5865F2)
        embed.description = cart_summary(cart)
        
        if cart:
            tot_val = cart_total(cart)
            embed.add_field(name="💰 Итого", value=f"**{format_price(tot_val)} {cfg['currency_name']}**")
            await interaction.response.send_message(embed=embed, view=CartView(interaction.user.id), ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

class ClearCartButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🗑️ Очистить корзину", style=discord.ButtonStyle.danger, custom_id="clear_cart_btn")

    async def callback(self, interaction: discord.Interaction):
        carts = get_carts()
        uid = str(interaction.user.id)
        carts[uid] = {}
        save_carts(carts)
        await interaction.response.send_message("🗑️ Корзина полностью очищена!", ephemeral=True)

class CartView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        
        carts = get_carts()
        cart = carts.get(str(user_id), {})
        
        if cart:
            self.add_item(RemoveItemSelect(user_id))
            self.add_item(CartClearAllButton(user_id))

class RemoveItemSelect(discord.ui.Select):
    def __init__(self, user_id: int):
        self.user_id = user_id
        carts = get_carts()
        cart = carts.get(str(user_id), {})
        items = get_items()
        item_map = {i["id"]: i for i in items}
        
        options = []
        for item_id, qty_units in cart.items():
            if item_id in item_map:
                it = item_map[item_id]
                per_qty = it.get("per_qty", 1)
                total_items = round(qty_units * per_qty)
                
                # Показываем детальное количество в корзине
                packs = total_items // per_qty
                rem_items = total_items % per_qty
                
                unit_str = "стак." if per_qty == 64 else "компл."
                if per_qty == 1:
                    unit_str = "шт."
                    
                qty_parts = []
                if packs > 0:
                    qty_parts.append(f"{packs} {unit_str}")
                if rem_items > 0 or not qty_parts:
                    qty_parts.append(f"{rem_items} шт.")
                
                qty_display = " + ".join(qty_parts)
                    
                options.append(
                    discord.SelectOption(
                        label=f"Удалить: {it['name']} ({qty_display})",
                        value=item_id,
                        emoji=it.get("emoji", "🗑️"),
                        description=f"Полностью убрать этот предмет из корзины"
                    )
                )
                
        if not options:
            options.append(discord.SelectOption(label="Корзина пуста", value="empty_cart"))
            
        super().__init__(
            placeholder="🗑️ Выбери товар для удаления из корзины...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"cart_remove_select_{user_id}"
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty_cart":
            await interaction.response.send_message("❌ Ваша корзина пуста!", ephemeral=True)
            return

        item_id = self.values[0]
        carts = get_carts()
        uid = str(interaction.user.id)
        
        if uid in carts and item_id in carts[uid]:
            del carts[uid][item_id]
            save_carts(carts)

        cfg = get_config()
        cart = carts.get(uid, {})
        
        embed = discord.Embed(title="🛒 Ваша корзина", color=0x5865F2)
        embed.description = cart_summary(cart)
        
        if cart:
            tot_val = cart_total(cart)
            embed.add_field(name="💰 Итого", value=f"**{format_price(tot_val)} {cfg['currency_name']}**")
            await interaction.response.edit_message(content="✅ Предмет успешно удален!", embed=embed, view=CartView(interaction.user.id))
        else:
            await interaction.response.edit_message(content="🗑️ Ваша корзина теперь пуста!", embed=embed, view=None)

class CartClearAllButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(
            label="🗑️ Очистить всё", 
            style=discord.ButtonStyle.danger, 
            custom_id=f"cart_clear_all_btn_{user_id}"
        )
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        carts = get_carts()
        uid = str(interaction.user.id)
        carts[uid] = {}
        save_carts(carts)
        
        embed = discord.Embed(title="🛒 Ваша корзина", color=0x5865F2)
        embed.description = "_Корзина пуста_"
        
        await interaction.response.edit_message(content="🗑️ Корзина полностью очищена!", embed=embed, view=None)

class CheckoutView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📦 Оформить заказ", style=discord.ButtonStyle.success, custom_id="checkout_btn")
    async def checkout(self, interaction: discord.Interaction, button: discord.ui.Button):
        carts = get_carts()
        uid = str(interaction.user.id)
        cart = carts.get(uid, {})
        if not cart:
            await interaction.response.send_message("❌ Твоя корзина пуста! Сначала добавь предметы в канале магазина.", ephemeral=True)
            return
        await interaction.response.send_modal(CheckoutModal(cart))

class CheckoutModal(discord.ui.Modal, title="📦 Оформление заказа"):
    minecraft_nick = discord.ui.TextInput(
        label="Ник в Minecraft",
        placeholder="Введи свой ник...",
        max_length=32
    )
    delivery_location = discord.ui.TextInput(
        label="Место доставки",
        placeholder="Например: координаты X Z, спавн, мой дом...",
        max_length=100
    )
    comment = discord.ui.TextInput(
        label="Комментарий (необязательно)",
        placeholder="Любые пожелания...",
        required=False,
        max_length=200,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, cart):
        super().__init__()
        self.cart = cart

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_config()
        if not cfg.get("orders_category_id"):
            await interaction.response.send_message("❌ Бот не настроен! Обратитесь к администратору.", ephemeral=True)
            return

        category = interaction.guild.get_channel(int(cfg["orders_category_id"]))
        if not category:
            await interaction.response.send_message("❌ Категория заказов не найдена!", ephemeral=True)
            return

        # Проверка остатков на складе перед оформлением канала заказа
        items = get_items()
        item_map = {i["id"]: i for i in items}
        for item_id, qty_units in self.cart.items():
            if item_id in item_map:
                it = item_map[item_id]
                stock = it.get("stock", -1)
                per_qty = it.get("per_qty", 1)
                total_needed_items = round(qty_units * per_qty)
                
                if stock != -1 and stock < total_needed_items:
                    await interaction.response.send_message(
                        f"❌ Ошибка! Товара {it['emoji']} **{it['name']}** недостаточно для твоего заказа.\n"
                        f"Доступно на складе: `{stock} шт.`, а ты пытаешься заказать: `{total_needed_items} шт.`.\n\n"
                        f"Пожалуйста, очисти корзину и собери доступное количество.",
                        ephemeral=True
                    )
                    return

        orders = get_orders()
        order_id = str(len(orders) + 1).zfill(4)
        order_num = f"{cfg['order_prefix']}-{order_id}"

        # Создание каналов заказа
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        if cfg.get("delivery_role_id"):
            delivery_role = interaction.guild.get_role(int(cfg["delivery_role_id"]))
            if delivery_role:
                overwrites[delivery_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if cfg.get("admin_role_id"):
            admin_role = interaction.guild.get_role(int(cfg["admin_role_id"]))
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await category.create_text_channel(
            name=f"📦-{order_num}",
            overwrites=overwrites
        )

        tot_val = cart_total(self.cart)
        tot_str = format_price(tot_val)

        embed = discord.Embed(
            title=f"📦 Заказ #{order_id}",
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 Покупатель", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        embed.add_field(name="🎮 Ник в MC", value=f"`{self.minecraft_nick.value}`", inline=True)
        embed.add_field(name="📍 Доставка", value=self.delivery_location.value, inline=True)
        embed.add_field(name="🛒 Состав заказа", value=cart_summary(self.cart), inline=False)
        embed.add_field(name="💰 Итого", value=f"**{tot_str} {cfg['currency_name']}**", inline=True)
        if self.comment.value:
            embed.add_field(name="💬 Комментарий", value=self.comment.value, inline=False)
        embed.set_footer(text=f"ID: {order_id}")

        ping_text = ""
        if cfg.get("delivery_role_id"):
            delivery_role = interaction.guild.get_role(int(cfg["delivery_role_id"]))
            if delivery_role:
                ping_text = f"{delivery_role.mention} "

        order_msg = await channel.send(
            content=f"{ping_text}Новый заказ от {interaction.user.mention}!",
            embed=embed,
            view=OrderActionsView(order_id, interaction.user.id, phase="new")
        )

        # Сохраняем заказ в базу
        orders[order_id] = {
            "user_id": interaction.user.id,
            "channel_id": channel.id,
            "message_id": order_msg.id,
            "nick": self.minecraft_nick.value,
            "location": self.delivery_location.value,
            "comment": self.comment.value,
            "cart": self.cart,
            "status": "new",
            "created_at": datetime.utcnow().isoformat()
        }
        save_orders(orders)

        # Очищаем корзину покупателя
        carts = get_carts()
        carts[str(interaction.user.id)] = {}
        save_carts(carts)

        await interaction.response.send_message(
            f"✅ Заказ **#{order_id}** успешно оформлен! Ожидай, с тобой свяжутся.",
            ephemeral=True
        )

        try:
            dm_embed = discord.Embed(
                title="📦 Заказ принят!",
                description=f"Твой заказ **#{order_id}** успешно создан и ожидает сборки.\n\n{cart_summary(self.cart)}\n\n💰 **Итого: {tot_str} {cfg['currency_name']}**",
                color=0x57F287
            )
            await interaction.user.send(embed=dm_embed)
        except Exception:
            pass

class OrderActionsView(discord.ui.View):
    def __init__(self, order_id: str, user_id: int, phase: str = "new"):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.user_id = user_id

        if phase == "new":
            self.add_item(StartOrderButton(order_id, user_id))
            self.add_item(DeclineOrderButton(order_id, user_id, phase))
        elif phase == "in_progress":
            self.add_item(CompleteOrderButton(order_id, user_id))
            self.add_item(DeclineOrderButton(order_id, user_id, phase))

class StartOrderButton(discord.ui.Button):
    def __init__(self, order_id, user_id):
        super().__init__(label="▶️ Начать сборку", style=discord.ButtonStyle.primary, custom_id=f"start_{order_id}")
        self.order_id = order_id
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        cfg = get_config()
        orders = get_orders()
        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ Заказ не найден.", ephemeral=True)
            return

        order["status"] = "in_progress"
        order["worker_id"] = interaction.user.id
        save_orders(orders)

        msg = interaction.message
        if msg.embeds:
            embed = msg.embeds[0]
            embed.color = discord.Color.blue()
            embed.add_field(name="⚙️ Исполнитель", value=interaction.user.mention, inline=True)

        ping_text = ""
        if cfg.get("delivery_role_id"):
            delivery_role = interaction.guild.get_role(int(cfg["delivery_role_id"]))
            if delivery_role:
                ping_text = f"{delivery_role.mention} "

        await interaction.message.edit(
            content=f"{ping_text}Заказ #{self.order_id} **взят в работу** исполнителем {interaction.user.mention}!",
            view=OrderActionsView(self.order_id, self.user_id, phase="in_progress")
        )

        buyer = interaction.guild.get_member(self.user_id)
        if buyer:
            try:
                dm_embed = discord.Embed(
                    title="⚙️ Заказ в обработке",
                    description=f"Твой заказ **#{self.order_id}** взят в работу!\nИсполнитель: **{interaction.user}**\n\n Ожидайте",
                    color=0x5865F2
                )
                await buyer.send(embed=dm_embed)
            except Exception:
                pass

        await interaction.response.send_message(f"✅ Ты взял заказ #{self.order_id} в работу!", ephemeral=True)

class CompleteOrderButton(discord.ui.Button):
    def __init__(self, order_id, user_id):
        super().__init__(label="✅ Выполнен", style=discord.ButtonStyle.success, custom_id=f"complete_{order_id}")
        self.order_id = order_id
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        orders = get_orders()
        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ Заказ не найден.", ephemeral=True)
            return

        # ─── СПИСАНИЕ ТОВАРА СО СКЛАДА ПРИ ВЫПОЛНЕНИИ ЗАКАЗА ───
        items = get_items()
        item_map = {i["id"]: i for i in items}
        cart = order.get("cart", {})

        for item_id, qty_units in cart.items():
            if item_id in item_map:
                it = item_map[item_id]
                stock = it.get("stock", -1)
                per_qty = it.get("per_qty", 1)
                total_deduct_items = round(qty_units * per_qty)
                
                if stock != -1:
                    it["stock"] = max(0, stock - total_deduct_items)
        
        save_items(items)

        order["status"] = "completed"
        save_orders(orders)

        await interaction.message.edit(
            content=f"✅ Заказ **#{self.order_id}** выполнен и доставлен исполнителем {interaction.user.mention}!",
            view=None
        )

        # Моментально обновляем витрину магазина с новыми остатками склада
        cfg = get_config()
        asyncio.create_task(refresh_shop_message(interaction.guild, cfg))

        buyer = interaction.guild.get_member(self.user_id)
        if buyer:
            try:
                dm_embed = discord.Embed(
                    title="✅ Заказ выполнен!",
                    description=f"Твой заказ **#{self.order_id}** успешно доставлен!\nСпасибо за покупку! 🎉",
                    color=0x57F287
                )
                await buyer.send(embed=dm_embed)
            except Exception:
                pass

        await interaction.response.send_message("✅ Заказ отмечен выполненным, остатки на складе успешно обновлены!", ephemeral=True)
        await asyncio.sleep(30)
        try:
            await interaction.channel.delete(reason=f"Заказ #{self.order_id} выполнен")
        except Exception:
            pass

class DeclineOrderButton(discord.ui.Button):
    def __init__(self, order_id, user_id, phase):
        super().__init__(label="❌ Отклонить", style=discord.ButtonStyle.danger, custom_id=f"decline_{order_id}_{phase}")
        self.order_id = order_id
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DeclineModal(self.order_id, self.user_id))

class DeclineModal(discord.ui.Modal, title="Причина отклонения"):
    reason = discord.ui.TextInput(
        label="Причина",
        placeholder="Укажи причину отклонения заказа...",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, order_id, user_id):
        super().__init__()
        self.order_id = order_id
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        orders = get_orders()
        order = orders.get(self.order_id)
        if order:
            order["status"] = "declined"
            save_orders(orders)

        await interaction.message.edit(
            content=f"❌ Заказ **#{self.order_id}** отклонён пользователем {interaction.user.mention}.",
            view=None
        )

        buyer = interaction.guild.get_member(self.user_id)
        if buyer:
            try:
                dm_embed = discord.Embed(
                    title="❌ Заказ отклонён",
                    description=f"К сожалению, твой заказ **#{self.order_id}** был отклонён.\n\n**Причина:** {self.reason.value}",
                    color=0xED4245
                )
                await buyer.send(embed=dm_embed)
            except Exception:
                pass

        await interaction.response.send_message("✅ Заказ отклонён, покупатель уведомлён.", ephemeral=True)
        await asyncio.sleep(15)
        try:
            await interaction.channel.delete(reason=f"Заказ #{self.order_id} отклонён")
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="⚙️ Выбери раздел настроек...",
        options=[
            discord.SelectOption(label="📢 Каналы", value="channels", emoji="📢", description="Настройка каналов магазина и заказов"),
            discord.SelectOption(label="👥 Роли", value="roles", emoji="👥", description="Роли доставщиков и администраторов"),
            discord.SelectOption(label="🎨 Оформление", value="appearance", emoji="🎨", description="Название, описание, валюта"),
            discord.SelectOption(label="📦 Предметы", value="items", emoji="📦", description="Управление товарами"),
            discord.SelectOption(label="📈 Управление запасами", value="stock_manage", emoji="📈", description="Быстро настроить остаток товаров на складе"),
            discord.SelectOption(label="🔄 Обновить каналы", value="refresh", emoji="🔄", description="Переотправить сообщения в каналы"),
        ]
    )
    async def settings_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        section = select.values[0]
        cfg = get_config()

        if section == "channels":
            embed = discord.Embed(title="📢 Настройка каналов", color=0x5865F2)
            embed.add_field(name="Канал магазина", value=f"<#{cfg['shop_channel_id']}>" if cfg['shop_channel_id'] else "❌ Не задан", inline=True)
            embed.add_field(name="Канал оформления", value=f"<#{cfg['checkout_channel_id']}>" if cfg['checkout_channel_id'] else "❌ Не задан", inline=True)
            embed.add_field(name="Категория заказов", value=f"<#{cfg['orders_category_id']}>" if cfg['orders_category_id'] else "❌ Не задана", inline=True)
            embed.set_footer(text="Используй кнопки ниже для изменения")
            await interaction.response.send_message(embed=embed, ephemeral=True, view=ChannelSettingsView())

        elif section == "roles":
            embed = discord.Embed(title="👥 Настройка ролей", color=0x5865F2)
            embed.add_field(name="Роль доставщика", value=f"<@&{cfg['delivery_role_id']}>" if cfg['delivery_role_id'] else "❌ Не задана", inline=True)
            embed.add_field(name="Роль администратора", value=f"<@&{cfg['admin_role_id']}>" if cfg['admin_role_id'] else "❌ Не задана", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True, view=RoleSettingsView())

        elif section == "appearance":
            embed = discord.Embed(title="🎨 Оформление магазина", color=0x5865F2)
            embed.add_field(name="Название магазина", value=cfg["shop_title"], inline=True)
            embed.add_field(name="Валюта", value=cfg["currency_name"], inline=True)
            embed.add_field(name="Описание", value=cfg["shop_description"], inline=False)
            embed.set_footer(text="Нажми кнопку для изменения")
            await interaction.response.send_message(embed=embed, ephemeral=True, view=AppearanceSettingsView())

        elif section == "items":
            items = get_items()
            embed = discord.Embed(title="📦 Список предметов", color=0x5865F2)
            lines = []
            for it in items:
                stock = it.get("stock", -1)
                per_qty = it.get("per_qty", 1)
                stock_str = "∞ (Бесконечно)" if stock == -1 else f"{stock} шт."
                
                price_text = f"{it['price']} {cfg['currency_name']} за {per_qty} шт."
                lines.append(f"{it['emoji']} **{it['name']}** — {price_text} | Запас: `{stock_str}` | `{it['id']}`")
            embed.description = "\n".join(lines) if lines else "_Предметов нет_"
            embed.set_footer(text="Используй кнопки для управления товарами")
            await interaction.response.send_message(embed=embed, ephemeral=True, view=ItemsSettingsView())

        elif section == "stock_manage":
            embed = discord.Embed(
                title="📈 Управление запасами на складе", 
                description="Выбери товар из списка ниже, чтобы изменить его остаток на складе.\n\n*Укажи `-1`, если хочешь сделать товар бесконечным.*",
                color=0x5865F2
            )
            await interaction.response.send_message(embed=embed, ephemeral=True, view=ItemStockSelectView())

        elif section == "refresh":
            await interaction.response.send_message("🔄 Обновляю сообщения в каналах...", ephemeral=True)
            await refresh_shop_message(interaction.guild, cfg)
            await refresh_checkout_message(interaction.guild, cfg)
            await interaction.edit_original_response(content="✅ Сообщения в каналах обновлены!")

class ChannelSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Задать канал магазина", style=discord.ButtonStyle.primary)
    async def set_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetChannelModal("shop_channel_id", "Канал магазина"))

    @discord.ui.button(label="Задать канал оформления", style=discord.ButtonStyle.primary)
    async def set_checkout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetChannelModal("checkout_channel_id", "Канал оформления заказов"))

    @discord.ui.button(label="Задать категорию заказов", style=discord.ButtonStyle.primary)
    async def set_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetChannelModal("orders_category_id", "Категория для каналов заказов"))

class SetChannelModal(discord.ui.Modal):
    channel_id = discord.ui.TextInput(label="ID канала/категории", placeholder="Правый клик → Копировать ID", max_length=20)

    def __init__(self, key, title_text):
        super().__init__(title=f"Изменить: {title_text}")
        self.key = key

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_config()
        try:
            cfg[self.key] = int(self.channel_id.value)
            save_config(cfg)
            await interaction.response.send_message(f"✅ Сохранено! `{self.key}` = `{self.channel_id.value}`", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Неверный ID! Укажи числовой ID канала.", ephemeral=True)

class RoleSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Задать роль доставщика", style=discord.ButtonStyle.primary)
    async def set_delivery(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetRoleModal("delivery_role_id", "Роль доставщика"))

    @discord.ui.button(label="Задать роль администратора", style=discord.ButtonStyle.primary)
    async def set_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetRoleModal("admin_role_id", "Роль администратора"))

class SetRoleModal(discord.ui.Modal):
    role_id = discord.ui.TextInput(label="ID роли", placeholder="Правый клик на роль → Копировать ID", max_length=20)

    def __init__(self, key, title_text):
        super().__init__(title=f"Изменить: {title_text}")
        self.key = key

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_config()
        try:
            cfg[self.key] = int(self.role_id.value)
            save_config(cfg)
            await interaction.response.send_message(f"✅ Сохранено!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Неверный ID!", ephemeral=True)

class AppearanceSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Изменить оформление", style=discord.ButtonStyle.primary)
    async def change_appearance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AppearanceModal())

class AppearanceModal(discord.ui.Modal, title="Оформление магазина"):
    shop_title = discord.ui.TextInput(label="Название магазина", max_length=100)
    shop_description = discord.ui.TextInput(label="Описание", style=discord.TextStyle.paragraph, max_length=300)
    currency_name = discord.ui.TextInput(label="Название валюты", placeholder="рублей / монет / алмазов...", max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_config()
        cfg["shop_title"] = self.shop_title.value
        cfg["shop_description"] = self.shop_description.value
        cfg["currency_name"] = self.currency_name.value
        save_config(cfg)
        await interaction.response.send_message("✅ Оформление обновлено! Не забудь обновить каналы через настройки.", ephemeral=True)

class ItemsSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="➕ Добавить предмет", style=discord.ButtonStyle.success)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddItemModal())

    @discord.ui.button(label="➖ Удалить предмет", style=discord.ButtonStyle.danger)
    async def remove_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🗑️ Удаление товара",
            description="Выбери предмет из выпадающего меню ниже, чтобы удалить его из базы данных.",
            color=0xED4245
        )
        await interaction.response.send_message(embed=embed, view=ItemDeleteSelectView(), ephemeral=True)

class AddItemModal(discord.ui.Modal, title="Добавить предмет"):
    item_id = discord.ui.TextInput(label="ID предмета (латиницей)", placeholder="oak_log", max_length=50)
    item_name = discord.ui.TextInput(label="Название", placeholder="Дубовое бревно", max_length=50)
    item_emoji = discord.ui.TextInput(label="Эмодзи", placeholder="🪵", max_length=5)
    item_price = discord.ui.TextInput(label="Цена (например: 50 или 2/64)", placeholder="50 или 2/64", max_length=15)
    item_desc = discord.ui.TextInput(label="Описание", placeholder="Прочные дубовые бревна стаками", max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        items = get_items()
        
        # Парсим слэш-формат цены (например, "2/64")
        price_val = self.item_price.value.strip()
        price = 1
        per_qty = 1
        
        if "/" in price_val:
            try:
                p_part, q_part = price_val.split("/")
                price = int(p_part.strip())
                per_qty = int(q_part.strip())
                if price <= 0 or per_qty <= 0:
                    raise ValueError()
            except ValueError:
                await interaction.response.send_message("❌ Неверный формат цены! Используйте число или формат цена/количество.", ephemeral=True)
                return
        else:
            try:
                price = int(price_val)
                if price <= 0:
                    raise ValueError()
            except ValueError:
                await interaction.response.send_message("❌ Цена должна быть положительным числом!", ephemeral=True)
                return

        new_item = {
            "id": self.item_id.value.lower().replace(" ", "_"),
            "name": self.item_name.value,
            "emoji": self.item_emoji.value,
            "price": price,
            "per_qty": per_qty,
            "description": self.item_desc.value,
            "stock": -1
        }
        items.append(new_item)
        save_items(items)
        
        cfg = get_config()
        await interaction.response.send_message(f"✅ Предмет **{self.item_name.value}** добавлен! Обновляю витрину...", ephemeral=True)
        await refresh_shop_message(interaction.guild, cfg)
        await interaction.edit_original_response(content=f"✅ Предмет **{self.item_name.value}** добавлен, и витрина успешно обновлена!")

class ItemDeleteSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ItemDeleteSelectMenu())

class ItemDeleteSelectMenu(discord.ui.Select):
    def __init__(self):
        items = get_items()
        options = []
        used_ids = set()

        for it in items:
            if it["id"] in used_ids:
                continue
            if len(options) >= 25:
                break
            
            stock = it.get("stock", -1)
            stock_str = "∞ (Бесконечно)" if stock == -1 else f"{stock} шт."
            options.append(
                discord.SelectOption(
                    label=f"Удалить: {it['name']}",
                    value=it["id"],
                    emoji=it.get("emoji", "🗑️"),
                    description=f"ID: {it['id']} | Запас: {stock_str}"
                )
            )
            used_ids.add(it["id"])

        if not options:
            options.append(discord.SelectOption(label="Список товаров пуст", value="empty_db"))

        super().__init__(
            placeholder="🗑️ Выбери товар для удаления...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="items_delete_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty_db":
            await interaction.response.send_message("❌ У вас нет созданных предметов!", ephemeral=True)
            return

        item_id = self.values[0]
        items = get_items()
        
        new_items = [i for i in items if i["id"] != item_id]
        save_items(new_items)

        cfg = get_config()
        await interaction.response.send_message(f"✅ Предмет `{item_id}` успешно удален из магазина! Обновляю витрину...", ephemeral=True)
        await refresh_shop_message(interaction.guild, cfg)
        await interaction.edit_original_response(content=f"✅ Предмет `{item_id}` успешно удален из магазина!")

class ItemStockSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ItemStockSelectMenu())

class ItemStockSelectMenu(discord.ui.Select):
    def __init__(self):
        items = get_items()
        options = []
        used_ids = set()

        for it in items:
            if it["id"] in used_ids:
                continue
            if len(options) >= 25:
                break
            
            stock = it.get("stock", -1)
            stock_str = "∞ (Бесконечно)" if stock == -1 else f"{stock} шт."
            options.append(
                discord.SelectOption(
                    label=f"{it['name']} (Остаток: {stock_str})",
                    value=it["id"],
                    description=f"ID: {it['id']} | Цена: {it['price']}",
                    emoji=it.get("emoji", "📦")
                )
            )
            used_ids.add(it["id"])

        super().__init__(
            placeholder="📈 Выбери предмет для изменения остатка...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="stock_item_select"
        )

    async def callback(self, interaction: discord.Interaction):
        item_id = self.values[0]
        items = get_items()
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            await interaction.response.send_message("❌ Предмет не найден.", ephemeral=True)
            return
        await interaction.response.send_modal(SetStockModal(item))

class SetStockModal(discord.ui.Modal):
    def __init__(self, item):
        super().__init__(title=f"Запас: {item['name']}")
        self.item = item
        
        self.stock_input = discord.ui.TextInput(
            label="Новое количество на складе (в шт.)",
            placeholder="Например: 320 (или -1 для бесконечного количества)",
            default=str(item.get("stock", -1)),
            max_length=10,
            required=True
        )
        self.add_item(self.stock_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_stock = int(self.stock_input.value)
            if new_stock < -1:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("❌ Пожалуйста, введи корректное целое число (-1 или больше)!", ephemeral=True)
            return

        items = get_items()
        for it in items:
            if it["id"] == self.item["id"]:
                it["stock"] = new_stock
                break
        save_items(items)

        stock_text = "бесконечно" if new_stock == -1 else f"{new_stock} шт."
        await interaction.response.send_message(
            f"✅ Количество товара **{self.item['name']}** успешно изменено на **{stock_text}**!",
            ephemeral=True
        )
        
        cfg = get_config()
        await refresh_shop_message(interaction.guild, cfg)

# ══════════════════════════════════════════════════════════════════════════════
# CHANNEL REFRESH HELPERS (PAGINATED)
# ══════════════════════════════════════════════════════════════════════════════

async def update_shop_message(message: discord.Message, cfg, page: int):
    items = get_items()
    total_pages = max(1, (len(items) - 1) // 8 + 1)
    
    embed = discord.Embed(
        title=cfg["shop_title"],
        description=cfg["shop_description"],
        color=0x57F287
    )
    
    start_idx = page * 8
    end_idx = start_idx + 8
    page_items = items[start_idx:end_idx]
    
    items_lines = []
    used_ids = set()
    for it in page_items:
        if it["id"] in used_ids:
            continue
        stock = it.get("stock", -1)
        per_qty = it.get("per_qty", 1)
        
        if stock == -1:
            stock_str = "∞ (Бесконечно)"
        else:
            stock_units = stock // per_qty
            stock_str = f"{stock_units} стак." if per_qty == 64 else f"{stock_units} компл."
            if stock_units == 0:
                stock_str = "🔴 Закончился"
            
        price_text = f"{it['price']} {cfg['currency_name']} за {per_qty} шт."
            
        items_lines.append(
            f"{it['emoji']} **{it['name']}** — {price_text}\n"
            f"├ Наличие: `{stock_str}` (всего {stock if stock != -1 else '∞'} шт.)\n"
            f"└ {it.get('description','')}"
        )
        used_ids.add(it["id"])
        
    items_text = "\n\n".join(items_lines)
    embed.add_field(name=f"📋 Доступные товары (Страница {page + 1}/{total_pages})", value=items_text or "_Товаров на этой странице нет_", inline=False)
    embed.set_footer(text=f"Страница {page + 1}/{total_pages} • Выбери товар из меню ниже")
    
    await message.edit(embed=embed, view=ShopView(page=page))

async def refresh_shop_message(guild, cfg):
    if not cfg.get("shop_channel_id"):
        return
    channel = guild.get_channel(int(cfg["shop_channel_id"]))
    if not channel:
        return
        
    await channel.purge(limit=10)
    
    items = get_items()
    total_pages = max(1, (len(items) - 1) // 8 + 1)
    
    embed = discord.Embed(
        title=cfg["shop_title"],
        description=cfg["shop_description"],
        color=0x57F287
    )
    
    page = 0
    start_idx = page * 8
    end_idx = start_idx + 8
    page_items = items[start_idx:end_idx]
    
    items_lines = []
    used_ids = set()
    for it in page_items:
        if it["id"] in used_ids:
            continue
        stock = it.get("stock", -1)
        per_qty = it.get("per_qty", 1)
        
        if stock == -1:
            stock_str = "∞ (Бесконечно)"
        else:
            stock_units = stock // per_qty
            stock_str = f"{stock_units} стак." if per_qty == 64 else f"{stock_units} компл."
            if stock_units == 0:
                stock_str = "🔴 Закончился"
            
        price_text = f"{it['price']} {cfg['currency_name']} за {per_qty} шт."
            
        items_lines.append(
            f"{it['emoji']} **{it['name']}** — {price_text}\n"
            f"├ Наличие: `{stock_str}` (всего {stock if stock != -1 else '∞'} шт.)\n"
            f"└ {it.get('description','')}"
        )
        used_ids.add(it["id"])
        
    items_text = "\n\n".join(items_lines)
    embed.add_field(name=f"📋 Доступные товары (Страница 1/{total_pages})", value=items_text or "_Товаров нет_", inline=False)
    embed.set_footer(text=f"Страница 1/{total_pages} • Выбери товар из меню ниже")
    
    await channel.send(embed=embed, view=ShopView(page=0))

async def refresh_checkout_message(guild, cfg):
    if not cfg.get("checkout_channel_id"):
        return
    channel = guild.get_channel(int(cfg["checkout_channel_id"]))
    if not channel:
        return
    embed = discord.Embed(
        title="📦 Оформление заказа",
        description="Нажми кнопку ниже, заполни форму с ником и адресом доставки, и твой заказ будет создан!",
        color=0x5865F2
    )
    embed.add_field(name="ℹ️ Как это работает", value="1️⃣ Добавь предметы в канале магазина\n2️⃣ Нажми «Оформить заказ» и заполни форму\n3️⃣ Ожидай уведомления в личных сообщениях", inline=False)
    await channel.purge(limit=10)
    await channel.send(embed=embed, view=CheckoutView())

# ─── COMMANDS ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup", description="Первоначальная настройка бота (только для администраторов)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Настройки магазина",
        description="Используй меню ниже для настройки бота.",
        color=0x5865F2
    )
    await interaction.response.send_message(embed=embed, view=SettingsView(), ephemeral=True)

@bot.tree.command(name="stock", description="Быстро изменить количество товара в наличии на складе")
@app_commands.checks.has_permissions(manage_messages=True)
async def stock_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📈 Управление запасами на складе", 
        description="Выбери товар из выпадающего меню ниже, чтобы мгновенно изменить его количество.\n\n*Укажи `-1`, если хочешь сделать товар бесконечным.*",
        color=0x5865F2
    )
    await interaction.response.send_message(embed=embed, ephemeral=True, view=ItemStockSelectView())

@bot.tree.command(name="refresh", description="Обновить сообщения в каналах магазина")
@app_commands.checks.has_permissions(administrator=True)
async def refresh(interaction: discord.Interaction):
    cfg = get_config()
    await interaction.response.defer(ephemeral=True)
    await refresh_shop_message(interaction.guild, cfg)
    await refresh_checkout_message(interaction.guild, cfg)
    await interaction.followup.send("✅ Каналы обновлены!", ephemeral=True)

@bot.tree.command(name="orders", description="Показать список активных заказов")
@app_commands.checks.has_permissions(manage_messages=True)
async def orders_list(interaction: discord.Interaction):
    orders = get_orders()
    active = {oid: o for oid, o in orders.items() if o["status"] in ("new", "in_progress")}
    if not active:
        await interaction.response.send_message("📭 Нет активных заказов.", ephemeral=True)
        return
    embed = discord.Embed(title="📦 Активные заказы", color=0xFEE75C)
    for oid, o in list(active.items())[:10]:
        status_emoji = "🟡" if o["status"] == "new" else "🔵"
        embed.add_field(
            name=f"{status_emoji} Заказ #{oid}",
            value=f"<@{o['user_id']}> | Ник: `{o['nick']}`",
            inline=True
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Бот запущен: {bot.user}")
    bot.add_view(ShopView())
    bot.add_view(CheckoutView())
    try:
        synced = await bot.tree.sync()
        print(f"✅ Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Укажи DISCORD_TOKEN в переменных окружения или .env файле!")
        exit(1)
    bot.run(TOKEN)