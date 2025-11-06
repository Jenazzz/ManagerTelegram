import asyncio
import aiosqlite
from telethon import TelegramClient, events
from telethon.tl.types import ChatParticipantAdmin, ChatParticipantCreator, ChannelParticipantAdmin, ChannelParticipantCreator
from config import API_ID, API_HASH, BOT_TOKEN, DATABASE_PATH, AUTO_SYNC_CHAT_ID, ADMIN_USER_ID

client = TelegramClient('bot_session', API_ID, API_HASH)

async def init_database():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_deleted BOOLEAN DEFAULT FALSE
            )
        ''')
        await db.commit()

async def add_user_to_db(user_id, chat_id, username, first_name, last_name):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute('''
            INSERT OR IGNORE INTO users (user_id, chat_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, chat_id, username, first_name, last_name))
        await db.commit()

async def get_users_count():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM users')
        result = await cursor.fetchone()
        return result[0]

async def get_all_users():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute('SELECT user_id, chat_id FROM users')
        return await cursor.fetchall()

async def get_users_in_chat(chat_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute('SELECT user_id FROM users WHERE chat_id = ?', (chat_id,))
        return [row[0] for row in await cursor.fetchall()]

async def sync_chat_members(chat_id):
    try:
        participants = await client.get_participants(chat_id)
        existing_in_db = await get_users_in_chat(chat_id)
        new_users_count = 0
        
        for user in participants:
            if not user.bot and user.id not in existing_in_db:
                await add_user_to_db(
                    user.id,
                    chat_id,
                    user.username or "",
                    user.first_name or "",
                    user.last_name or ""
                )
                new_users_count += 1
        
        return new_users_count
    except Exception as e:
        print(f"Ошибка синхронизации чата: {e}")
        return 0

async def is_admin(chat_id, user_id):
    try:
        participant = await client.get_permissions(chat_id, user_id)
        return participant.is_admin
    except:
        return False

@client.on(events.ChatAction)
async def member_handler(event):
    try:
        if hasattr(event, 'user_added') and event.user_added:
            user = await event.get_user()
            if not user.bot:
                await add_user_to_db(
                    user.id, 
                    event.chat_id, 
                    user.username or "", 
                    user.first_name or "", 
                    user.last_name or ""
                )
                print(f"Добавлен пользователь {user.first_name} (ID: {user.id}) в БД")
        
        elif hasattr(event, 'user_joined') and event.user_joined:
            user = await event.get_user()
            if not user.bot:
                await add_user_to_db(
                    user.id, 
                    event.chat_id, 
                    user.username or "", 
                    user.first_name or "", 
                    user.last_name or ""
                )
                print(f"Присоединился пользователь {user.first_name} (ID: {user.id}) в БД")
        
        elif hasattr(event, 'users') and event.users:
            for user in event.users:
                if not user.bot:
                    await add_user_to_db(
                        user.id, 
                        event.chat_id, 
                        user.username or "", 
                        user.first_name or "", 
                        user.last_name or ""
                    )
                    print(f"Добавлен в группу пользователь {user.first_name} (ID: {user.id}) в БД")
    except Exception as e:
        print(f"Ошибка при обработке нового участника: {e}")

@client.on(events.NewMessage)
async def message_handler(event):
    if event.is_group and hasattr(event, 'message') and hasattr(event.message, 'action'):
        action = event.message.action
        if hasattr(action, 'users'):
            for user_id in action.users:
                try:
                    user = await client.get_entity(user_id)
                    if not user.bot:
                        await add_user_to_db(
                            user.id, 
                            event.chat_id, 
                            user.username or "", 
                            user.first_name or "", 
                            user.last_name or ""
                        )
                        print(f"Новый участник через action: {user.first_name} (ID: {user.id})")
                except Exception as e:
                    print(f"Ошибка получения пользователя {user_id}: {e}")

@client.on(events.NewMessage(pattern='/cleanusers'))
async def clean_handler(event):
    if not event.is_group:
        return
    
    if not await is_admin(event.chat_id, event.sender_id):
        return
    
    try:
        me = await client.get_me()
        chat_perms = await client.get_permissions(event.chat_id, me)
        
        if not chat_perms.ban_users:
            return
        
        users_in_db = await get_all_users()
        deleted_count = 0
        removed_count = 0
        
        await client.send_message(ADMIN_USER_ID, "Начинаю очистку удаленных пользователей...")
        
        for user_id, chat_id in users_in_db:
            if chat_id != event.chat_id:
                continue
                
            try:
                user = await client.get_entity(user_id)
                if user.deleted:
                    deleted_count += 1
                    try:
                        await client.kick_participant(event.chat_id, user_id)
                        removed_count += 1
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"Не удалось удалить пользователя {user_id}: {e}")
            except Exception:
                deleted_count += 1
                try:
                    await client.kick_participant(event.chat_id, user_id)
                    removed_count += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"Не удалось удалить пользователя {user_id}: {e}")
        
        await client.send_message(ADMIN_USER_ID, f"Очистка завершена\nПроверено: {deleted_count}\nУдалено: {removed_count}")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await client.send_message(ADMIN_USER_ID, "Ошибка при очистке участников")

@client.on(events.NewMessage(pattern='/dbusers'))
async def dbusers_handler(event):
    if not event.is_group:
        return
    
    if not await is_admin(event.chat_id, event.sender_id):
        return
    
    try:
        chat_users = await get_users_in_chat(event.chat_id)
        await client.send_message(ADMIN_USER_ID, f"Пользователей в БД для чата: {len(chat_users)}")
    except Exception as e:
        print(f"Ошибка: {e}")
        await client.send_message(ADMIN_USER_ID, "Ошибка при получении данных из БД")



async def main():
    await init_database()
    await client.start(bot_token=BOT_TOKEN)
    print("Бот запущен")
    
    if AUTO_SYNC_CHAT_ID:
        print(f"Автосинхронизация id:{AUTO_SYNC_CHAT_ID}...")
        try:
            new_count = await sync_chat_members(AUTO_SYNC_CHAT_ID)
            total = len(await get_users_in_chat(AUTO_SYNC_CHAT_ID))
            print(f"добавлено {new_count}, всего {total}")
        except Exception as e:
            print(f"Ошибка автосинхронизации: {e}")
    else:
        print("AUTO_SYNC_CHAT_ID не установлен")
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
