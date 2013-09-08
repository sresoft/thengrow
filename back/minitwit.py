# -*- coding: utf-8 -*-
"""
    MiniTwit
    ~~~~~~~~

    A microblogging application written with Flask and sqlite3.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import time
from sqlite3 import dbapi2 as sqlite3
from hashlib import md5
from datetime import datetime
from flask import Flask, request, session, url_for, redirect, \
     render_template, abort, g, flash, _app_ctx_stack
from werkzeug import check_password_hash, generate_password_hash
from simplemodel import *
from mymodels import *

# configuration
DATABASE = 'minitwit.db'
PER_PAGE = 30
DEBUG = True
SECRET_KEY = 'development key'

# create our little application :)
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('MINITWIT_SETTINGS', silent=True)


def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    top = _app_ctx_stack.top
    if not hasattr(top, 'sqlite_db'):
        top.sqlite_db = sqlite3.connect(app.config['DATABASE'])
        top.sqlite_db.row_factory = sqlite3.Row
    return top.sqlite_db


@app.teardown_appcontext
def close_database(exception):
    """Closes the database again at the end of the request."""
    top = _app_ctx_stack.top
    if hasattr(top, 'sqlite_db'):
        top.sqlite_db.close()


def init_db():
    """Creates the database tables."""
    if User.table_exists() == False:
        User.create_table()
        Message.create_table()
        Follower.create_table()
        """
        with app.open_resource(schema, mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()
        """


def query_db(query, args=(), one=False):
    """Queries the database and returns a list of dictionaries."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


def get_user_id(username):
    """Convenience method to look up the id for a username."""
    try:
        rv = User.select().where(User.username == username).get()
    except User.DoesNotExist:
        rv = None
    return rv


def format_datetime(timestamp):
    """Format a timestamp for display."""
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d @ %H:%M')


def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    return 'http://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
        (md5(email.strip().lower().encode('utf-8')).hexdigest(), size)


@app.before_request
def before_request():
    top = _app_ctx_stack.top

    if not hasattr(top, 'db_connection'):
        database.connect()
        top.db_connection = database

    g.user = None
    if 'user_id' in session:
        try:
            g.user = User.select().where(User.user == session['user_id']).get()
        except User.DoesNotExist:
            g.user = None

@app.route('/')
def timeline():
    """Shows a users timeline or if no user is logged in it will
    redirect to the public timeline.  This timeline shows the user's
    messages as well as all the messages of followed users.
    """
    if not g.user:
        return redirect(url_for('public_timeline'))

    subquery = Follower.select(Follower.whom).where(Follower.who == session['user_id'])
    messages = Message.select(Message,User).join(User,on=(Message.author == User.user)).where(User.user == session['user_id'] | User.user << subquery).execute()
    return render_template('timeline.html', messages=messages)


@app.route('/public')
def public_timeline():
    """Displays the latest messages of all users."""
    messages = Message.select(User,Message).\
                    join(User,on=(Message.author == User.user)).\
                        order_by(Message.pub_date.desc()).limit(PER_PAGE).execute()
    return render_template('timeline.html', messages=messages)


@app.route('/<username>')
def user_timeline(username):
    """Display's a users tweets."""
    try:
        profile_user = User.select().where(User.username == username).get()
    except User.DoesNotExist:
        profile_user = None

    if profile_user is None:
        abort(404)
    followed = False
    if g.user:
        followed = Follower.select(Follower.who,Follower.whom).where(Follower.who == session['user_id'] & Follower.whom == profile_user.user).exists()
        followed = followed is not None
        messages = Message.select(Message,User).join(User,on=(Message.author == User.user)).order_by(Message.pub_date.desc()).limit(PER_PAGE).execute()
    else:
        return redirect(url_for('login'))
    return render_template('timeline.html', messages=messages, followed=followed,
            profile_user=profile_user)


@app.route('/<username>/follow')
def follow_user(username):
    """Adds the current user as follower of the given user."""
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)

    Follower.create(who=session['user_id'],whom=whom_id)

    flash('You are now following "%s"' % username)
    return redirect(url_for('user_timeline', username=username))


@app.route('/<username>/unfollow')
def unfollow_user(username):
    """Removes the current user as follower of the given user."""
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)

    Follower.delete().where(Follower.who == session['user_id'] & Follower.whom == whom_id).execute()

    flash('You are no longer following "%s"' % username)
    return redirect(url_for('user_timeline', username=username))


@app.route('/add_message', methods=['POST'])
def add_message():
    """Registers a new message for the user."""
    if 'user_id' not in session:
        abort(401)
    if request.form['text']:
        Message.create(author=session['user_id'],text=request.form['text'],
                        pub_date=int(time.time()))
        """
        db = get_db()
        db.execute('''insert into message (author_id, text, pub_date)
          values (?, ?, ?)''', (session['user_id'], request.form['text'],
                                int(time.time())))
        db.commit()
        """
        flash('Your message was recorded')
    return redirect(url_for('timeline'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Logs the user in."""
    if g.user:
        return redirect(url_for('timeline'))
    error = None
    if request.method == 'POST':
        try:
            user = User.select() \
                       .where(User.username == request.form['username']).get()
        except User.DoesNotExist:
            user = None
        flash(user)
        #user = query_db('''select * from user where
        #    username = ?''', [request.form['username']], one=True)
        flash(request.form['password'])
        if user is None:
            error = 'Invalid username'
        elif not check_password_hash(user.pw_hash,
                                     request.form['password']):
            error = 'Invalid password'
        else:
            flash('You were logged in')
            session['user_id'] = user.user
           # return redirect(url_for('timeline'))
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registers the user."""
    if g.user:
        return redirect(url_for('timeline'))
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = 'You have to enter a username'
        elif not request.form['email'] or \
                 '@' not in request.form['email']:
            error = 'You have to enter a valid email address'
        elif not request.form['password']:
            error = 'You have to enter a password'
        elif request.form['password'] != request.form['password2']:
            error = 'The two passwords do not match'
        elif get_user_id(request.form['username']) is not None:
            error = 'The username is already taken'
        else:
            User.create(username=request.form['username'],email=request.form['email'],pw_hash=generate_password_hash(request.form['password']))

            flash('You were successfully registered and can login now')
            return redirect(url_for('login'))
    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    """Logs the user out."""
    flash('You were logged out')
    session.pop('user_id', None)
    return redirect(url_for('public_timeline'))


# add some filters to jinja
app.jinja_env.filters['datetimeformat'] = format_datetime
app.jinja_env.filters['gravatar'] = gravatar_url


if __name__ == '__main__':
    init_db()
    app.run()
