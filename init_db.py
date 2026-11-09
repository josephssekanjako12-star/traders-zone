import sqlite3
import os

def init_db():
    # Check if we are on PythonAnywhere
    if os.environ.get('PYTHONANYWHERE_DOMAIN'):
        db_path = '/home/Archer/traderszone/traderszone.db'
    else:
        db_path = 'traderszone.db'
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, bio TEXT DEFAULT 'Forex & Crypto Trader', avatar_path TEXT, name TEXT, email TEXT, last_seen DATETIME)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, image_path TEXT, views INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS likes (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, post_id INTEGER NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, user_id INTEGER NOT NULL, text_content TEXT, image_path TEXT, sticker TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS comment_likes (id INTEGER PRIMARY KEY AUTOINCREMENT, comment_id INTEGER, user_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bookmarks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, post_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS follows (id INTEGER PRIMARY KEY AUTOINCREMENT, follower_id INTEGER, following_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS post_views (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, user_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, sender_id INTEGER, type TEXT, post_id INTEGER, is_read INTEGER DEFAULT 0, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER, receiver_id INTEGER, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, image_paths TEXT, is_read INTEGER DEFAULT 0, reply_to_id INTEGER, is_edited INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, creator_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, avatar_path TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER, user_id INTEGER, last_read_message_id INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, sender_id INTEGER, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, image_paths TEXT, reply_to_id INTEGER, is_edited INTEGER DEFAULT 0)''')

    conn.commit()
    conn.close()
    print("All 13 tables initialized successfully!")

if __name__ == '__main__':
    init_db()
