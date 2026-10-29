import random # Add this for the OTP
from flask import Flask, render_template, request, redirect, url_for, session,jsonify
# ... (keep other imports)
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session,jsonify
import re
from markupsafe import Markup
import uuid
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__)
app.secret_key = 'traders_zone_secret_key_2026'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

def get_db_connection():
    # Use /data folder on Render, or local folder on iSH
    db_path = '/data/traderszone.db' if os.environ.get('RENDER') else 'traderszone.db'
    conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row 
    return conn

@app.before_request
def update_last_seen():
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute('UPDATE users SET last_seen = ? WHERE username = ?', (now, session['user_id']))
            conn.commit()
            conn.close()
        except sqlite3.OperationalError:
            # If the database is locked, just ignore it and try again next click
            pass

@app.template_filter('local_time')
def local_time_filter(value, format="%H:%M"):
    if not value: return ""
    try:
        # SQLite stores time as 'YYYY-MM-DD HH:MM:SS' in UTC
        utc_dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        # Add 3 hours for Uganda (EAT, UTC+3)
        local_dt = utc_dt + timedelta(hours=3)
        return local_dt.strftime(format)
    except Exception as e:
        return value # If it fails, just return the original string

@app.template_filter('chat_time')
def chat_time_filter(value):
    if not value: return ""
    try:
        utc_dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        local_dt = utc_dt + timedelta(hours=3)
        now_local = datetime.utcnow() + timedelta(hours=3)
        
        if local_dt.date() == now_local.date():
            return local_dt.strftime("Today %H:%M")
        elif local_dt.date() == (now_local - timedelta(days=1)).date():
            return local_dt.strftime("Yesterday %H:%M")
        else:
            return local_dt.strftime("%b %d %H:%M")
    except:
        return value

@app.template_filter('linkify')
def linkify_hashtags(text):
    if not text: return ""
    safe_text = str(Markup.escape(text))
    # Capture the word WITHOUT the #, and put it in the URL
    linked_text = re.sub(r'#(\w+)', r'<a href="/hashtag/\1" style="color: #00ffaa; text-decoration: none; font-weight: bold;">#\1</a>', safe_text)
    return Markup(linked_text)

@app.context_processor
def inject_global_vars():
    if 'user_id' in session:
        conn = get_db_connection()
        me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
        if me:
            # DM Unread Count
            msg_count = conn.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0', (me['id'],)).fetchone()[0]
            
            # Group Unread Count
            group_count = conn.execute('''
                SELECT COUNT(*) FROM group_messages gm
                JOIN group_members gmem ON gm.group_id = gmem.group_id
                WHERE gmem.user_id = ? AND gm.id > gmem.last_read_message_id
            ''', (me['id'],)).fetchone()[0]
            
            # Notification Count
            notif_count = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', (me['id'],)).fetchone()[0]
            
            conn.close()
            return dict(total_unread=(msg_count + group_count), total_notifs=notif_count)
    return dict(total_unread=0, total_notifs=0)

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    # 1. Get the page number from the URL (e.g., ?page=2), default is 1
    page = request.args.get('page', 1, type=int)
    limit = 5
    offset = (page - 1) * limit
    
    # 2. Add LIMIT and OFFSET to the SQL query
    posts = conn.execute('''
        SELECT posts.*, users.username, users.avatar_path, posts.image_path,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) as like_count,
        (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id) as comment_count,
        posts.views,
        (SELECT COUNT(*) FROM follows WHERE follower_id = ? AND following_id = posts.user_id) as is_following,
        (SELECT COUNT(*) FROM bookmarks WHERE user_id = ? AND post_id = posts.id) as is_bookmarked
        FROM posts 
        JOIN users ON posts.user_id = users.id 
        ORDER BY is_following DESC, ((SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) * 2 + (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id) * 3 + posts.views) DESC, posts.timestamp DESC
        LIMIT ? OFFSET ?
    ''', (me['id'], me['id'], limit, offset)).fetchall()
    
    conn.close()
    
    # 3. If the request comes from our JavaScript (ajax), only return the post cards
    if request.args.get('ajax'):
        return render_template('_post_cards.html', posts=posts)
        
    return render_template('index.html', posts=posts)

@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        content = request.form.get('content', '')
        file = request.files.get('post_image')
        
        image_path = None
        if file and file.filename != '':
            if not allowed_file(file.filename):
                return "Error: Only images allowed!", 400
            filename = secure_filename(file.filename)
            filename = f"post_{session['user_id']}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = f"static/uploads/{filename}"
            
        conn = get_db_connection()
        user = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
        
        if user and (content.strip() or image_path):
            cursor = conn.execute('INSERT INTO posts (user_id, content, image_path) VALUES (?, ?, ?)', (user['id'], content, image_path))
            new_post_id = cursor.lastrowid
            
            # Break the long query into a variable to prevent terminal wrapping issues
            query = 'INSERT INTO notifications (user_id, sender_id, type, post_id) SELECT follower_id, ?, ?, ? FROM follows WHERE following_id = ?'
            conn.execute(query, (user['id'], 'new_post', new_post_id, user['id']))
                         
            conn.commit()
            
        conn.close()
        return redirect(url_for('index'))
        
    return render_template('create_post.html')

@app.route('/bookmark/<int:post_id>')
def bookmark(post_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    existing = conn.execute('SELECT * FROM bookmarks WHERE post_id = ? AND user_id = ?', (post_id, me['id'])).fetchone()
    if existing:
        conn.execute('DELETE FROM bookmarks WHERE post_id = ? AND user_id = ?', (post_id, me['id']))
    else:
        conn.execute('INSERT INTO bookmarks (post_id, user_id) VALUES (?, ?)', (post_id, me['id']))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/saved')
def saved():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    posts = conn.execute('''
        SELECT posts.*, users.username, users.avatar_path, posts.image_path,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) as like_count,
        (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id) as comment_count,
        posts.views, 
        (SELECT COUNT(*) FROM follows WHERE follower_id = ? AND following_id = posts.user_id) as is_following,
        (SELECT COUNT(*) FROM bookmarks WHERE user_id = ? AND post_id = posts.id) as is_bookmarked
        FROM posts JOIN bookmarks ON posts.id = bookmarks.post_id
        JOIN users ON posts.user_id = users.id
        WHERE bookmarks.user_id = ?
        ORDER BY bookmarks.id DESC
    ''', (me['id'], me['id'], me['id'])).fetchall()
    
    conn.close()
    return render_template('saved.html', posts=posts)

@app.route('/hashtag/<tag>')
def hashtag(tag):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    search_term = f"%{tag}%"
    posts = conn.execute('''
        SELECT posts.*, users.username, users.avatar_path, posts.image_path,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) as like_count,
        (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id) as comment_count,
        posts.views, 
        (SELECT COUNT(*) FROM follows WHERE follower_id = ? AND following_id = posts.user_id) as is_following,
        (SELECT COUNT(*) FROM bookmarks WHERE user_id = ? AND post_id = posts.id) as is_bookmarked
        FROM posts JOIN users ON posts.user_id = users.id
        WHERE posts.content LIKE ?
        ORDER BY posts.timestamp DESC
    ''', (me['id'], me['id'], search_term)).fetchall()
    conn.close()
    return render_template('index.html', posts=posts, hashtag=f"#{tag}")

@app.route('/trending')
def trending():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    posts = conn.execute('SELECT content FROM posts').fetchall()
    conn.close()
    
    hashtags = {}
    for p in posts:
        if p['content']:
            tags = re.findall(r'(#\w+)', p['content'])
            for t in tags:
                t_lower = t.lower()
                hashtags[t_lower] = hashtags.get(t_lower, 0) + 1
                
    sorted_tags = sorted(hashtags.items(), key=lambda x: x[1], reverse=True)[:10]
    return render_template('trending.html', trending=sorted_tags)

@app.route('/like/<int:post_id>')
def like_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    user = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    if user:
        existing = conn.execute('SELECT * FROM likes WHERE post_id = ? AND user_id = ?', (post_id, user['id'])).fetchone()
        
        if existing:
            conn.execute('DELETE FROM likes WHERE post_id = ? AND user_id = ?', (post_id, user['id']))
        else:
            conn.execute('INSERT INTO likes (post_id, user_id) VALUES (?, ?)', (post_id, user['id']))
            
            post_owner = conn.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
            if post_owner and post_owner['user_id'] != user['id']:
                conn.execute('INSERT INTO notifications (user_id, sender_id, type, post_id) VALUES (?, ?, ?, ?)', 
                        (post_owner['user_id'], user['id'], 'like', post_id))
        conn.commit()
    conn.close()
    
    return redirect(request.referrer or url_for('index'))

@app.route('/follow/<username>')
def follow(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    target = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    
    if me and target and me['id'] != target['id']:
        existing = conn.execute('SELECT * FROM follows WHERE follower_id = ? AND following_id = ?', (me['id'], target['id'])).fetchone()
        
        if existing:
            # 1. Remove the follow
            conn.execute('DELETE FROM follows WHERE follower_id = ? AND following_id = ?', (me['id'], target['id']))
            
            # 2. Delete the old "followed you" notification so it doesn't stay there forever
            conn.execute('DELETE FROM notifications WHERE user_id = ? AND sender_id = ? AND type = ?', (target['id'], me['id'], 'follow'))
            
        else:
            # Add the follow
            conn.execute('INSERT INTO follows (follower_id, following_id) VALUES (?, ?)', (me['id'], target['id']))
            
            # Send the "follow" notification
            conn.execute('INSERT INTO notifications (user_id, sender_id, type) VALUES (?, ?, ?)', 
                         (target['id'], me['id'], 'follow'))
        conn.commit()
    conn.close()
    
    return redirect(request.referrer or url_for('index'))

@app.route('/like_comment/<int:comment_id>')
def like_comment(comment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    user = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    if user:
        existing = conn.execute('SELECT * FROM comment_likes WHERE comment_id = ? AND user_id = ?', (comment_id, user['id'])).fetchone()
        
        if existing:
            conn.execute('DELETE FROM comment_likes WHERE comment_id = ? AND user_id = ?', (comment_id, user['id']))
        else:
            conn.execute('INSERT INTO comment_likes (comment_id, user_id) VALUES (?, ?)', (comment_id, user['id']))
            
            comment_owner = conn.execute('SELECT user_id, post_id FROM comments WHERE id = ?', (comment_id,)).fetchone()
            
            if comment_owner and comment_owner['user_id'] != user['id']:
                conn.execute('INSERT INTO notifications (user_id, sender_id, type, post_id) VALUES (?, ?, ?, ?)', 
                             (comment_owner['user_id'], user['id'], 'like_comment', comment_owner['post_id']))
        conn.commit()
    conn.close()
    
    return redirect(request.referrer or url_for('index'))

@app.route('/post/<int:post_id>')
def view_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    # 1. Check if the user has already viewed this post
    has_viewed = conn.execute('SELECT * FROM post_views WHERE post_id = ? AND user_id = ?', (post_id, me['id'])).fetchone()
    
    # 2. If not, add the view and record it
    if not has_viewed:
        conn.execute('INSERT INTO post_views (post_id, user_id) VALUES (?, ?)', (post_id, me['id']))
        conn.execute('UPDATE posts SET views = views + 1 WHERE id = ?', (post_id,))
        conn.commit()
    
    # 3. Fetch the post (with author and like counts)
    post = conn.execute('''
        SELECT posts.*, users.username, users.avatar_path,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) as like_count
        FROM posts 
        JOIN users ON posts.user_id = users.id 
        WHERE posts.id = ?
    ''', (post_id,)).fetchone()
    
    # 4. Fetch the comments (with authors and like counts)
    comments = conn.execute('''
        SELECT comments.*, users.username, users.avatar_path,
        (SELECT COUNT(*) FROM comment_likes WHERE comment_likes.comment_id = comments.id) as like_count
        FROM comments 
        JOIN users ON comments.user_id = users.id 
        WHERE comments.post_id = ?
        ORDER BY comments.timestamp ASC
    ''', (post_id,)).fetchall()
    
    conn.close()
    
    if not post:
        return "Post not found", 404
        
    return render_template('post.html', post=post, comments=comments, my_id=me['id'])

@app.route('/add_comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    text_content = request.form.get('text_content', '')
    sticker = request.form.get('sticker', '')
    file = request.files.get('comment_image')
    
    image_path = None
    if file and file.filename != '':
        if not allowed_file(file.filename):
            return "Error: Only images_allowed in comments!", 400
        filename = secure_filename(file.filename)
        filename = f"comment_{post_id}_{session['user_id']}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_path = f"static/uploads/{filename}"
        
    conn = get_db_connection()
    user = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    if user:
        conn.execute('''
            INSERT INTO comments (post_id, user_id, text_content, image_path, sticker) 
            VALUES (?, ?, ?, ?, ?)
        ''', (post_id, user['id'], text_content, image_path, sticker))
        conn.commit()
    conn.close()
    
    return redirect(url_for('view_post', post_id=post_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form.get('confirm_password') # Get the new field
        
        # Check if passwords match
        if password != confirm_password:
            return render_template('register.html', error="Passwords do not match!")
        
        hashed_pw = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (name, username, email, password) VALUES (?, ?, ?, ?)', 
                         (name, username, email, hashed_pw))
            conn.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return render_template('register.html', error="Username or Email already exists!")
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/chats')
def chats():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    users = conn.execute('SELECT * FROM users WHERE username != ?', (session['user_id'],)).fetchall()
    
    chat_list = []
    for u in users:
        # Get unread count from this specific user
        unread = conn.execute('SELECT COUNT(*) FROM messages WHERE sender_id=? AND receiver_id=? AND is_read=0', (u['id'], me['id'])).fetchone()[0]
        
        # Get the very last message
        last_msg = conn.execute('''
            SELECT * FROM messages 
            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
            ORDER BY timestamp DESC LIMIT 1
        ''', (me['id'], u['id'], u['id'], me['id'])).fetchone()
        
        chat_list.append({'user': u, 'unread': unread, 'last_msg': last_msg})
        
    conn.close()
    return render_template('chats.html', chat_list=chat_list)

# Add this new route for the FAB
@app.route('/new_chat')
def new_chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users WHERE username != ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('new_chat.html', users=users)

@app.route('/chat_room/<username>')
def chat_room(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # 1. Connect to the database
    conn = get_db_connection()
    
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    them = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    
    if not them:
        conn.close()
        return "User not found", 404
        
    # 2. Determine if they are online (active in the last 5 minutes)
    is_online = False
    if them['last_seen']:
        them_last_seen = datetime.strptime(them['last_seen'], "%Y-%m-%d %H:%M:%S") + timedelta(hours=3)
        now = datetime.utcnow() + timedelta(hours=3)
        if (now - them_last_seen).total_seconds() < 300:
            is_online = True
        
    # 3. Mark messages as read
    conn.execute('UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?', (them['id'], me['id']))
    conn.commit()
        
    # 4. Fetch messages with the JOIN for avatars
    messages = conn.execute('''
        SELECT messages.id, messages.sender_id, messages.receiver_id, messages.content, 
               messages.image_paths, messages.timestamp, messages.is_read, messages.is_edited, messages.reply_to_id,
               users.avatar_path as sender_avatar,
               reply.content as reply_content, reply.image_paths as reply_images
        FROM messages 
        JOIN users ON messages.sender_id = users.id
        LEFT JOIN messages reply ON messages.reply_to_id = reply.id
        WHERE (messages.sender_id = ? AND messages.receiver_id = ?) 
           OR (messages.sender_id = ? AND messages.receiver_id = ?)
        ORDER BY messages.timestamp ASC
    ''', (me['id'], them['id'], them['id'], me['id'])).fetchall()
    conn.close()
    
    return render_template('chat_room.html', them=them, messages=messages, my_id=me['id'], is_online=is_online)

@app.route('/delete_message/<int:msg_id>', methods=['POST'])
def delete_message(msg_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    # Ensure the user owns the message before deleting
    conn.execute('DELETE FROM messages WHERE id = ? AND sender_id = ?', (msg_id, me['id']))
    conn.commit()
    conn.close()
    return redirect(request.referrer)

@app.route('/edit_message/<int:msg_id>', methods=['POST'])
def edit_message(msg_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    new_content = request.form.get('content')
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    conn.execute('UPDATE messages SET content = ?, is_edited = 1 WHERE id = ? AND sender_id = ?', (new_content, msg_id, me['id']))
    conn.commit()
    conn.close()
    return redirect(request.referrer)

@app.route('/reply_message/<int:msg_id>', methods=['POST'])
def reply_message(msg_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    # We will handle the reply logic by appending it to the text when we redirect
    return redirect(request.referrer)

@app.route('/send_message/<username>', methods=['POST'])
def send_message(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    content = request.form.get('content', '')
    files = request.files.getlist('images')
    reply_to = request.form.get('reply_to_id')
    
    if reply_to == "":
        reply_to = None
    
    image_paths = []
    for file in files:
        if file and file.filename != '':
            if not allowed_file(file.filename):
                return "Error: Only images are allowed in chats!", 400    
            filename = secure_filename(file.filename)
            filename = f"chat_{session['user_id']}_{uuid.uuid4().hex[:8]}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_paths.append(f"static/uploads/{filename}")
            
    image_paths_str = ",".join(image_paths) if image_paths else None
    
    if content.strip() or image_paths_str:
        conn = get_db_connection()
        me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
        them = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        
        if me and them:
            conn.execute('INSERT INTO messages (sender_id, receiver_id, content, image_paths, reply_to_id) VALUES (?, ?, ?, ?, ?)', 
                         (me['id'], them['id'], content, image_paths_str, reply_to))
            conn.commit()
        conn.close()
        
    return redirect(url_for('chat_room', username=username))

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    # Fetch notifications
    notifs = conn.execute('''
        SELECT n.*, u.username as sender_username, u.avatar_path as sender_avatar
        FROM notifications n
        JOIN users u ON n.sender_id = u.id
        WHERE n.user_id = ?
        ORDER BY n.timestamp DESC
    ''', (me['id'],)).fetchall()
    
    # Mark them as read
    conn.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (me['id'],))
    conn.commit()
    conn.close()
    
    return render_template('notifications.html', notifications=notifs)

@app.route('/api/unread_counts')
def api_unread_counts():
    if 'user_id' not in session:
        return jsonify({"messages": 0, "notifications": 0})
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    msg_count = conn.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0', (me['id'],)).fetchone()[0]
    group_count = conn.execute('''
        SELECT COUNT(*) FROM group_messages gm
        JOIN group_members gmem ON gm.group_id = gmem.group_id
        WHERE gmem.user_id = ? AND gm.id > gmem.last_read_message_id
    ''', (me['id'],)).fetchone()[0]
    
    notif_count = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', (me['id'],)).fetchone()[0]
    conn.close()
    return jsonify({"messages": msg_count + group_count, "notifications": notif_count})

@app.route('/api/latest_post_id')
def latest_post_id():
    if 'user_id' not in session:
        return jsonify({"latest_id": 0})
    conn = get_db_connection()
    result = conn.execute('SELECT MAX(id) as max_id FROM posts').fetchone()
    conn.close()
    return jsonify({"latest_id": result['max_id'] or 0})

@app.route('/my_profile')
def my_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    # Get user info
    user = conn.execute('SELECT * FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    # Get ONLY this user's posts
    posts = conn.execute('''
        SELECT posts.*, users.username, users.avatar_path, posts.image_path,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) as like_count,
        (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id) as comment_count
        FROM posts 
        JOIN users ON posts.user_id = users.id 
        WHERE users.username = ?
        ORDER BY posts.timestamp DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('my_profile.html', user=user, posts=posts)

@app.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    
    # Get my info
    me = conn.execute('SELECT * FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    # Get Followers (People following me)
    followers = conn.execute('''
        SELECT u.username, u.avatar_path FROM follows f
        JOIN users u ON f.follower_id = u.id
        WHERE f.following_id = ?
    ''', (me['id'],)).fetchall()
    
    # Get Following (People I am following)
    following = conn.execute('''
        SELECT u.username, u.avatar_path FROM follows f
        JOIN users u ON f.following_id = u.id
        WHERE f.follower_id = ?
    ''', (me['id'],)).fetchall() 
    saved_count = conn.execute('SELECT COUNT(*) FROM bookmarks WHERE user_id = ?', (me['id'],)).fetchone()[0]    

    conn.close()
    return render_template('settings.html', user=me, followers=followers, following=following, saved_count=saved_count)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    new_bio = request.form.get('bio', '')
    file = request.files.get('avatar')
    
    conn = get_db_connection()
    
    # Update Bio
    conn.execute('UPDATE users SET bio = ? WHERE username = ?', (new_bio, session['user_id']))
    
    # Update Avatar if uploaded
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        filename = f"avatar_{session['user_id']}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        avatar_path = f"static/uploads/{filename}"
        conn.execute('UPDATE users SET avatar_path = ? WHERE username = ?', (avatar_path, session['user_id']))
        
    conn.commit()
    conn.close()
    return redirect(url_for('settings'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['username']
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid username or password! Please try again.")
            
    return render_template('login.html')

@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    query = request.args.get('q', '')
    conn = get_db_connection()
    users = []
    posts = []
    if query:
        users = conn.execute('SELECT * FROM users WHERE username LIKE ?', ('%' + query + '%',)).fetchall()
        posts = conn.execute('''
            SELECT posts.*, users.username, users.avatar_path, posts.image_path 
            FROM posts 
            JOIN users ON posts.user_id = users.id 
            WHERE posts.content LIKE ? 
            ORDER BY posts.timestamp DESC
        ''', ('%' + query + '%',)).fetchall()
    conn.close()
    return render_template('search.html', query=query, users=users, posts=posts)

@app.route('/user/<username>')
def user_profile(username):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    
    # 1. Get the user you are viewing
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return "User not found", 404
        
    # 2. Get their posts
    posts = conn.execute('''
        SELECT posts.*, users.username, users.avatar_path, posts.image_path,
        (SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) as like_count,
        (SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id) as comment_count
        FROM posts 
        JOIN users ON posts.user_id = users.id 
        WHERE users.username = ?
        ORDER BY posts.timestamp DESC
    ''', (username,)).fetchall()
    
    # 3. Check if you are following them
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    is_following = conn.execute('SELECT * FROM follows WHERE follower_id = ? AND following_id = ?', (me['id'], user['id'])).fetchone()
    
    followers_count = conn.execute('SELECT COUNT(*) FROM follows WHERE following_id = ?', (user['id'],)).fetchone()[0]
    following_count = conn.execute('SELECT COUNT(*) FROM follows WHERE follower_id = ?', (user['id'],)).fetchone()[0]
    # 4. Close the database connection ONLY AFTER all queries are done
    conn.close()
    return render_template('user_profile.html', user=user, posts=posts, is_following=is_following, followers_count=followers_count, following_count=following_count)    

@app.route('/groups')
def groups():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    my_groups = conn.execute('''
        SELECT groups.*, group_members.last_read_message_id FROM groups
        JOIN group_members ON groups.id = group_members.group_id
        WHERE group_members.user_id = ?
    ''', (me['id'],)).fetchall()
    
    groups_data = []
    for g in my_groups:
        last_msg = conn.execute('''
            SELECT group_messages.*, users.username, users.avatar_path 
            FROM group_messages JOIN users ON group_messages.sender_id = users.id 
            WHERE group_id = ? ORDER BY timestamp DESC LIMIT 1
        ''', (g['id'],)).fetchone()
        
        # Calculate unread for this group
        unread = conn.execute('SELECT COUNT(*) FROM group_messages WHERE group_id = ? AND id > ?', (g['id'], g['last_read_message_id'])).fetchone()[0]
        
        groups_data.append({'group': g, 'last_msg': last_msg, 'unread': unread})
        
    conn.close()
    return render_template('groups.html', groups=groups_data)

@app.route('/create_group', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    if request.method == 'POST':
        group_name = request.form.get('group_name')
        selected_users = request.form.getlist('members')
        
        # NOTICE: This if statement must be indented INSIDE the POST block
        if group_name:
            cursor = conn.execute('INSERT INTO groups (name, creator_id) VALUES (?, ?)', (group_name, me['id']))
            group_id = cursor.lastrowid
            
            conn.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', (group_id, me['id']))
            
            for user_id in selected_users:
                conn.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', (group_id, user_id))
                conn.execute('INSERT INTO notifications (user_id, sender_id, type, post_id) VALUES (?, ?, ?, ?)', (user_id, me['id'], 'group_add', group_id))
                
            conn.commit()
            conn.close()
            return redirect(url_for('groups'))
            
    # This part runs if it's a GET request
    # Only fetch users who are FOLLOWING me
    users = conn.execute('SELECT users.* FROM users JOIN follows ON users.id = follows.follower_id WHERE follows.following_id = ?', (me['id'],)).fetchall()
    conn.close()
    return render_template('create_group.html', users=users)

@app.route('/group_chat/<int:group_id>')
def group_chat(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    is_member = conn.execute('SELECT * FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, me['id'])).fetchone()
    if not is_member:
        conn.close()
        return "You are not a member of this group.", 403
        
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    
    latest_msg = conn.execute('SELECT MAX(id) as max_id FROM group_messages WHERE group_id = ?', (group_id,)).fetchone()
    if latest_msg['max_id']:
        conn.execute('UPDATE group_members SET last_read_message_id = ? WHERE group_id = ? AND user_id = ?', (latest_msg['max_id'], group_id, me['id']))
        conn.commit()
    
    # Calculate Members and Online Members
    all_members = conn.execute('SELECT users.last_seen FROM group_members JOIN users ON group_members.user_id = users.id WHERE group_members.group_id = ?', (group_id,)).fetchall()
    total_members = len(all_members)
    
    online_count = 0
    now = datetime.utcnow() + timedelta(hours=3)
    for m in all_members:
        if m['last_seen']:
            last_seen = datetime.strptime(m['last_seen'], "%Y-%m-%d %H:%M:%S") + timedelta(hours=3)
            if (now - last_seen).total_seconds() < 300:
                online_count += 1

    # Fetch messages with reply info
    messages = conn.execute('''
        SELECT group_messages.*, users.username, users.avatar_path,
        reply.content as reply_content, reply_user.username as reply_sender
        FROM group_messages 
        JOIN users ON group_messages.sender_id = users.id 
        LEFT JOIN group_messages reply ON group_messages.reply_to_id = reply.id
        LEFT JOIN users reply_user ON reply.sender_id = reply_user.id
        WHERE group_messages.group_id = ? ORDER BY group_messages.timestamp ASC
    ''', (group_id,)).fetchall()
    
    conn.close()
    return render_template('group_chat.html', group=group, messages=messages, my_id=me['id'], total_members=total_members, online_count=online_count)

@app.route('/send_group_message/<int:group_id>', methods=['POST'])
def send_group_message(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    content = request.form.get('content', '')
    file = request.files.get('group_image')
    
    image_path = None
    if file and file.filename != '':
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"group_{group_id}_{session['user_id']}_{uuid.uuid4().hex[:8]}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = f"static/uploads/{filename}"
    
    if content.strip() or image_path:
        conn = get_db_connection()
        me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
        conn.execute('INSERT INTO group_messages (group_id, sender_id, content, image_paths) VALUES (?, ?, ?, ?)', 
                     (group_id, me['id'], content, image_path))
        conn.commit()
        conn.close()
        
    return redirect(url_for('group_chat', group_id=group_id))

@app.route('/delete_group_msg/<int:msg_id>', methods=['POST'])
def delete_group_msg(msg_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    msg = conn.execute('SELECT group_id, sender_id FROM group_messages WHERE id = ?', (msg_id,)).fetchone()
    if msg:
        group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (msg['group_id'],)).fetchone()
        # Permission: You are the sender OR you are the group creator
        if msg['sender_id'] == me['id'] or group['creator_id'] == me['id']:
            conn.execute('DELETE FROM group_messages WHERE id = ?', (msg_id,))
            conn.commit()
        conn.close()
        return redirect(url_for('group_chat', group_id=msg['group_id']))
    conn.close()
    return redirect(url_for('groups'))

@app.route('/edit_group_msg/<int:msg_id>', methods=['POST'])
def edit_group_msg(msg_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    new_content = request.form.get('content')
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    msg = conn.execute('SELECT group_id, sender_id FROM group_messages WHERE id = ?', (msg_id,)).fetchone()
    # Permission: You can ONLY edit your own messages
    if msg and msg['sender_id'] == me['id']:
        conn.execute('UPDATE group_messages SET content = ?, is_edited = 1 WHERE id = ?', (new_content, msg_id))
        conn.commit()
    conn.close()
    return redirect(url_for('group_chat', group_id=msg['group_id'] if msg else 1))

@app.route('/send_group_reply/<int:group_id>/<int:msg_id>', methods=['POST'])
def send_group_reply(group_id, msg_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    content = request.form.get('content', '')
    if content.strip():
        conn = get_db_connection()
        me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
        conn.execute('INSERT INTO group_messages (group_id, sender_id, content, reply_to_id) VALUES (?, ?, ?, ?)', (group_id, me['id'], content, msg_id))
        conn.commit()
        conn.close()
    return redirect(url_for('group_chat', group_id=group_id))

@app.route('/group_settings/<int:group_id>')
def group_settings(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        conn.close()
        return "Group not found", 404
        
    # Fetch all members of this group
    members = conn.execute('''
        SELECT users.id, users.username, users.avatar_path, users.last_seen 
        FROM group_members 
        JOIN users ON group_members.user_id = users.id 
        WHERE group_members.group_id = ?
    ''', (group_id,)).fetchall()
    
    conn.close()
    return render_template('group_settings.html', group=group, members=members, my_id=me['id'])

@app.route('/update_group_avatar/<int:group_id>', methods=['POST'])
def update_group_avatar(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
    
    
    if group and group['creator_id'] == me['id']:
        file = request.files.get('group_avatar')
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"group_{group_id}_{uuid.uuid4().hex[:8]}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = f"static/uploads/{filename}"
            conn.execute('UPDATE groups SET avatar_path = ? WHERE id = ?', (image_path, group_id))
            conn.commit()
            
    conn.close()
    return redirect(url_for('group_settings', group_id=group_id))

@app.route('/update_group_name/<int:group_id>', methods=['POST'])
def update_group_name(group_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    new_name = request.form.get('new_group_name', '').strip()
    
    if new_name:
        conn = get_db_connection()
        me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
        group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
        
        if group and group['creator_id'] == me['id']:
            conn.execute('UPDATE groups SET name = ? WHERE id = ?', (new_name, group_id))
            conn.commit()
            
        conn.close()
        
    return redirect(url_for('group_settings', group_id=group_id))

@app.route('/remove_group_member/<int:group_id>/<int:user_id>', methods=['POST'])
def remove_group_member(group_id, user_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    me = conn.execute('SELECT id FROM users WHERE username = ?', (session['user_id'],)).fetchone()
    group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
    
    
    if group and group['creator_id'] == me['id']:
        # Don't let the admin kick themselves
        if user_id != me['id']:
            conn.execute('DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id))
            conn.commit()
            
    conn.close()
    return redirect(url_for('group_settings', group_id=group_id))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user:
            # Generate a 6-digit OTP
            otp = str(random.randint(100000, 999999))
            session['reset_otp'] = otp
            session['reset_email'] = email
            print(f"\n\n=================================")
            print("YOUR OTP CODE IS: " + otp)
            print("=================================\n\n")
            return redirect(url_for('verify_otp'))
        else:
            return render_template('forgot_password.html', error="No account found with that email.")
    return render_template('forgot_password.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_email' not in session:
        return redirect(url_for('forgot_password'))
        
    if request.method == 'POST':
        entered_otp = request.form['otp']
        if entered_otp == session.get('reset_otp'):
            session['otp_verified'] = True
            return redirect(url_for('reset_password'))
        else:
            return render_template('verify_otp.html', error="Invalid OTP. Please check the terminal.")
    return render_template('verify_otp.html')

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified'):
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        new_password = request.form['password']
        hashed_pw = generate_password_hash(new_password)
        
        conn = get_db_connection()
        conn.execute('UPDATE users SET password = ? WHERE email = ?', (hashed_pw, session['reset_email']))
        conn.commit()
        conn.close()
        
        # Clear the reset session data
        session.pop('reset_otp', None)
        session.pop('reset_email', None)
        session.pop('otp_verified', None)
        
        return redirect(url_for('login'))
    return render_template('reset_password.html')

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8080)) # Use PORT env var or 8080 locally
    app.run(host='0.0.0.0', port=port)
