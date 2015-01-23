from flask import Flask, render_template, url_for, make_response, redirect, jsonify, request, g
from contextlib import closing
from datetime import datetime
import time
import requests
import sqlite3
import json
import os
from random import random

app = Flask(__name__)
app.config.update(
    DATABASE = 'base.db',
    DEBUG = False
)

# run once from bash to auto-setup tables
def init_db():
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


def connect_db():
    return sqlite3.connect(app.config['DATABASE'])


@app.before_request
def before_request():
    g.db = connect_db()


@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()


@app.route('/', methods = ['GET'])
def landing_page():
    redirect_uri = "http://vksmm.info" + url_for('parse_vk_responce')
    client_id = "4260316"
    link = "https://oauth.vk.com/authorize?"
    link += "client_id=" + client_id
    link += "&scope=groups"
    link += "&response_type=code&v=5.27"
    link += "&redirect_uri=" + redirect_uri
    return render_template('landing.html', link = link)


# vk auth module -- OK
@app.route('/vk_login', methods = ['GET'])
def parse_vk_responce():
    code = request.args.get('code')
    if code:
        try:
            client_id = "4260316"
            client_secret = "x9Qe9JKVfoTG57LMKUgH"
            redirect_uri = "http://vksmm.info" + url_for('parse_vk_responce')
            # render link and get auth_token, user_id
            req = "https://oauth.vk.com/access_token?"
            req += "client_id=" + client_id
            req += "&client_secret=" + client_secret
            req += "&code=" + code
            req += "&redirect_uri=" + redirect_uri
            res = requests.get(req).json()

            # personal data
            user_id = res["user_id"]
            access_token = res["access_token"]

            # load old sorting ...
            res = g.db.execute("select sort_type from userinfo where user_id = {0}".format(user_id)).fetchall()
            try:
                sort_type = res[0][0]
                if sort_type not in ['like', 'repo', 'comm']:
                    sort_type = 'like'
            except:
                sort_type = 'like'

            # delete old personal data first + save new 
            g.db.execute("delete from userinfo where user_id = {0}".format(user_id))
            g.db.execute("delete from groups where user_id = {0}".format(user_id))
            g.db.execute("insert into userinfo (user_id, auth_token, sort_type, last_seen) values ({0}, '{1}', '{2}', '{3}')".format(int(user_id), access_token, sort_type, datetime.now()))
            g.db.commit()
            
            # load fresh groups from account; 
            req = "https://api.vk.com/method/execute.get_all_groups?access_token=" + access_token
            buf = requests.get(req).json()["response"]
            group_ids = ",".join(str(xi) for xi in buf)
            
            req = "https://api.vk.com/method/groups.getById?group_ids={0}".format(group_ids)
            groups = requests.get(req).json()["response"]
            for item in groups:
                g.db.execute("insert into groups (user_id, group_id, screen_name, picture, added, is_old) values ({0}, {1}, '{2}', '{3}', {4}, 0)".format(int(user_id), int(item["gid"]), item["screen_name"], item["photo_medium"], int(time.time())))
                g.db.commit()
        
        except Exception as e:
            print "/vk_login err:", e
            return "error: {0}".format(e)
        return redirect(url_for('index_page', user_id = user_id, access_token = access_token))
    else:
        return "Something has gone wrong<br><a href='{0}'>go back to login page</a>".format(url_for('vk'))


# main page
@app.route('/index', methods = ['GET'])
def index_page():
    access_token = request.args.get('access_token')
    user_id = request.args.get('user_id')
    try:
        user_id = int(user_id)
    except:
        # may be render link here? 
        return "'user_id' error: int expected"
    group_id = request.args.get('group_id')
    offset = request.args.get('offset')
    sort_type = request.args.get('sort_type')
    if user_id and access_token:
        try:
            groups = g.db.execute("select group_id from groups where user_id = {0}".format(user_id)).fetchall()
            try:
                group_id = int(group_id)
            except Exception as e:
                group_id = groups[0][0]

            group_ids = ",".join("{0}".format(group[0]) for group in groups)
            if group_ids.find(str(group_id)) == -1:
                group_ids += ",{0}".format(group_id)
            
            req = "https://api.vk.com/method/groups.getById?group_ids=" + group_ids
            names = requests.get(req).json()["response"]

            # way to get data for loaded group
            current_group_name = None
            current_group_picture = None
            group_list = []
            append = group_list.append
            for name in names: # cut group name til 30 chars
                buf_group_name = name["name"]
                if len(buf_group_name) >= 30:
                    buf_group_name = buf_group_name[:27] + "..."
                
                append([name["gid"], buf_group_name, name["photo_medium"]])
                if str(name["gid"]) == str(group_id):
                    current_group_name = name["name"]
                    current_group_picture = name["photo_medium"]

            # UPDATE SORTING
            if sort_type in ['like', 'repo', 'comm']:
                g.db.execute("update userinfo set sort_type = '{0}', last_seen = '{1}' where user_id = {2}".format(sort_type, datetime.now(), user_id))
                g.db.commit()
            else:
                g.db.execute("update userinfo set last_seen = '{0}' where user_id = {1}".format(datetime.now(), user_id))
                g.db.commit()
                res = g.db.execute("select sort_type from userinfo where user_id = {0}".format(user_id)).fetchall()
                sort_type = res[0][0]

            try:
                offset = int(offset)
            except:
                offset = 0

            try:
                w = int(request.args.get('w'))
                h = int(request.args.get('h'))
                
                cols = int((w*0.8 - 235)/125) #x
                rows = int((h - 120.0)/120) #y
                count = rows*cols
                print "rows = {0}, cols = {1}, count = {2}".format(rows, cols, count)
            except Exception as e:
                print "w-h error: {0}".format(e)
                count = 35
            posts = g.db.execute("select like, repo, comm, link, picture from postinfo where group_id = {0} order by {1} desc limit {2} offset {3}".format(group_id, sort_type, count, offset*count)).fetchall()
            if posts:
                recomendation = None
            else:
                max_range = g.db.execute("select count(*) from groups").fetchall()[0][0]
                rlimit = int((h - 300)/36.0)  # isn't valid for the first run... add redirect back!
                if rlimit > max_range:
                    print "big screen :)"
                    rlimit = max_range - 1

                roffset = int((max_range-rlimit)*random()) + 1
                print "recomendations. offset:", roffset, " len groups:", len(groups)
                                                        # where is_old = 1  # <-- add this to production code
                groups = g.db.execute("select group_id from groups limit {0} offset {1}".format(rlimit, roffset)).fetchall()
                group_ids = ",".join("{0}".format(group[0]) for group in groups)
                req = "https://api.vk.com/method/groups.getById?group_ids=" + group_ids
                names = requests.get(req).json()["response"]

                recomendation = []
                append = recomendation.append
                for name in names: 
                    buf_group_name = name["name"]
                    if len(buf_group_name) >= 50:
                        buf_group_name = buf_group_name[:47] + "..."
                    append([name["gid"], buf_group_name, name["photo_medium"]])

            # load actual username
            try:
                req = "https://api.vk.com/method/execute.name_pic?access_token={0}&id={1}".format(access_token, user_id)
                response = requests.get(req).json()["response"]
                user_name = response["name"]
                avatar = response["picture"] # avatar 100px
            except:
                user_name = " "
                avatar = None

            # PAGE-NAVIGATION LINKS
            offset_prev = None
            if offset > 0: 
                offset_prev = url_for('index_page') + "?user_id={0}&access_token={1}&group_id={2}&offset={3}".format(user_id, access_token, group_id, offset - 1)

            offset_next = None
            count_postinfo = g.db.execute("select count(*) from postinfo where group_id = {0}".format(group_id)).fetchall()[0][0]
            if count*(offset + 1) < count_postinfo:
                offset_next = url_for('index_page') + "?user_id={0}&access_token={1}&group_id={2}&offset={3}".format(user_id, access_token, group_id, offset + 1)

            base_link = url_for('index_page') + "?user_id={0}&access_token={1}&group_id={2}&offset={3}&sort_type=".format(user_id, access_token, group_id, offset)

            # finaly load stats
            try:
                f = open("statistics.txt", "r")
                stats = json.loads(f.read())
                f.close()
            except:
                stats = None            
            return render_template("index.html", group_list = group_list, posts = posts, user_id = user_id, user_name = user_name, avatar = avatar,
                                   access_token = access_token, current_group_name = current_group_name, current_group_picture = current_group_picture,
                                   offset_prev = offset_prev, offset_next = offset_next, offset = offset, base_link = base_link, stats = stats,
                                   group_id = group_id, count_postinfo = count_postinfo, sort_type = sort_type, recomendation = recomendation)
        except Exception as e:
            return "Exception (index_page): {0}".format(e)
    else:
        return "'user_id' and 'access_token' were expected"


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'code': 404, 'error': 'Page not found', 'message': "{0}".format(error)}), 404)


if __name__ == '__main__':
    app.run(host='0.0.0.0')
