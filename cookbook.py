#!/usr/bin/env python
#
# Copyright 2011 Bret Taylor
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import aws
import base64
import datetime
import functools
import images
import json
import logging
import os.path
import random
import re
import string
import tornado.database
import tornado.escape
import tornado.httpclient
import tornado.ioloop
import tornado.web
import urllib
import urlparse

from tornado.options import define, options

define("aws_s3_bucket")
define("aws_cloudfront_host")
define("compiled_css_url")
define("compiled_jquery_url")
define("compiled_js_url")
define("config")
define("cookie_secret")
define("comments", type=bool, default=True)
define("debug", type=bool)
define("facebook_app_id")
define("facebook_app_secret")
define("facebook_canvas_id")
define("mysql_host")
define("mysql_database")
define("mysql_user")
define("mysql_password")
define("port", type=int, default=8080)
define("silent", type=bool)


class CookbookApplication(tornado.web.Application):
    def __init__(self):
        base_dir = os.path.dirname(__file__)
        settings = {
            "cookie_secret": options.cookie_secret,
            "static_path": os.path.join(base_dir, "static"),
            "template_path": os.path.join(base_dir, "templates"),
            "debug": options.debug,
            "ui_modules": {
                "RecipeList": RecipeList,
                "RecipeClips": RecipeClips,
                "ActivityStream": ActivityStream,
                "ActivityItem": ActivityItem,
                "RecipePhoto": RecipePhoto,
                "RecipeInfo": RecipeInfo,
                "RecipeActions": RecipeActions,
                "RecipeContext": RecipeContext,
                "Facepile": Facepile,
            },
        }
        tornado.web.Application.__init__(self, [
            tornado.web.url(r"/", HomeHandler, name="home"),
            tornado.web.url(r"/recipe/([^/]+)", RecipeHandler, name="recipe"),
            tornado.web.url(r"/category", CategoryHandler, name="category"),
            tornado.web.url(r"/cookbook/([^/]+)", CookbookHandler,
                            name="cookbook"),
            tornado.web.url(r"/edit", EditHandler, name="edit"),
            tornado.web.url(r"/a/login", LoginHandler, name="login"),
            tornado.web.url(r"/a/clip", ClipHandler, name="clip"),
            tornado.web.url(r"/a/cook", CookHandler, name="cook"),
            tornado.web.url(r"/a/upload", UploadHandler, name="upload"),
        ], **settings)


class BaseHandler(tornado.web.RequestHandler):
    @property
    def backend(self):
        return Backend.instance()

    def is_ajax(self):
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def get_current_user(self):
        uid = self.get_secure_cookie("uid")
        return self.backend.get_user(uid) if uid else None

    def get_login_url(self, next=None):
        if not next:
            next = self.request.full_url()
        if not next.startswith("http://") and not next.startswith("https://"):
            next = urlparse.urljoin(self.request.full_url(), next)
        if self.get_argument("code", None):
            return "http://" + self.request.host + \
                self.reverse_url("login") + "?" + urllib.urlencode({
                    "next": next,
                    "code": self.get_argument("code"),
                })
        redirect_uri = "http://" + self.request.host + \
            self.reverse_url("login") + "?" + urllib.urlencode({"next": next})
        if self.get_argument("code", None):
            args["code"] = self.get_argument("code")
        return "https://www.facebook.com/dialog/oauth?" + urllib.urlencode({
            "client_id": options.facebook_app_id,
            "redirect_uri": redirect_uri,
            "scope": "offline_access,publish_actions",
        })

    def write_json(self, obj):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(json.dumps(obj))

    def render(self, template, **kwargs):
        kwargs["error_message"] = self.get_secure_cookie("message")
        if kwargs["error_message"]:
            kwargs["error_message"] = base64.b64decode(kwargs["error_message"])
            self.clear_cookie("message")
        tornado.web.RequestHandler.render(self, template, **kwargs)

    def render_string(self, template, **kwargs):
        args = {
            "markdown": self.markdown,
            "options": options,
            "user_possessive": self.user_possessive,
            "user_link": self.user_link,
            "friend_list": self.friend_list,
        }
        args.update(kwargs)
        return tornado.web.RequestHandler.render_string(self, template, **args)

    def set_error_message(self, message):
        self.set_secure_cookie("message", base64.b64encode(message))

    def user_possessive(self, user):
        if user["gender"] == "male":
            return "his"
        else:
            return "her"

    def friend_list(self, friends, size=3):
        if len(friends) == 1:
            return self.user_link(friends[0], True, True)
        elif len(friends) > size + 1:
            return ", ".join(self.user_link(f, True, i == 0) for i, f in
                             enumerate(friends[:size])) + \
                   " and " + str(len(friends) - size) + " other friends"
        else:
            return ", ".join(self.user_link(f, True, i == 0) for i, f in
                             enumerate(friends[:len(friends) - 1])) + \
                   " and " + \
                   self.user_link(friends[len(friends) - 1], True, False)

    def user_link(self, user, you=False, capitalize=True):
        if you and self.current_user and self.current_user["id"] == user["id"]:
            name = "You" if capitalize else "you"
        else:
            name = user["name"]
        return '<a href="' + user["link"] + '" class="name">' + \
            tornado.escape.xhtml_escape(name) + '</a>'

    def markdown(self, text):
        text = re.sub(r"\n\s*\n", "</p><p>",
                      tornado.escape.xhtml_escape(text.strip()))
        text = re.sub(r"\n", "<br>", text)
        return '<p>' + text + '</p>'


class HomeHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        all_recipes = self.backend.get_recently_clipped_recipes(
            [self.current_user["id"]])
        existing_ids = set(r["id"] for r in all_recipes)
        friends_recent = self.backend.get_recently_clipped_recipes(
            self.backend.get_friend_ids(self.current_user), 10, existing_ids)
        user_recipe_ids = set(r["id"] for r in all_recipes)
        friends_recent = [r for r in friends_recent
                          if r["id"] not in user_recipe_ids]
        user_recent = all_recipes[:2] if friends_recent else all_recipes[:4]
        if not all_recipes:
            friends_recent = friends_recent[:6]
        elif len(all_recipes) < 4:
            friends_recent = friends_recent[:4]
        else:
            friends_recent = friends_recent[:2]
        if not all_recipes and len(friends_recent) < 2:
            self.render("home-empty.html")
            return
        self.render("home.html", all_recipes=all_recipes,
                    user_recent=user_recent, friends_recent=friends_recent)


class UploadHandler(BaseHandler):
    @tornado.web.authenticated
    @tornado.web.asynchronous
    def post(self):
        recipe = self.backend.get_recipe(int(self.get_argument("recipe")))
        if not recipe:
            raise tornado.web.HTTPError(404)
        if recipe["photo"] and recipe["author_id"] != self.current_user["id"]:
            raise tornado.web.HTTPError(403)
        full = images.resize_image(
            self.request.files.values()[0][0]["body"], max_width=800,
            max_height=800, quality=85)
        thumb = images.resize_image(
            self.request.files.values()[0][0]["body"], max_width=300,
            max_height=800, quality=85)
        resized = {"full": full, "thumb": thumb}
        if full["width"] < 300 or full["height"] < 300:
            self.set_error_message(
                "Recipe images must be at least 300 pixels wide and "
                "300 pixels tall.")
            self.redirect(self.reverse_url("recipe", recipe["slug"]))
            return
        thumb["uploaded"] = False
        full["uploaded"] = False
        self.backend.s3.put_cdn_content(
            data=thumb["data"], mime_type=thumb["mime_type"],
            callback=functools.partial(
                self.on_upload, "thumb", recipe, resized))
        self.backend.s3.put_cdn_content(
            data=full["data"], mime_type=full["mime_type"],
            callback=functools.partial(
                self.on_upload, "full", recipe, resized))

    def on_upload(self, image_size, recipe, images, hash):
        if not hash:
            raise tornado.web.HTTPError(500)
        images[image_size]["uploaded"] = True
        images[image_size]["hash"] = hash
        if images["thumb"]["uploaded"] and images["full"]["uploaded"]:
            self.backend.save_photos(recipe, images["full"], images["thumb"])
            self.redirect(self.reverse_url("recipe", recipe["slug"]))
            url = "http://" + self.request.host + \
                self.reverse_url("recipe", recipe["slug"])
            # Force Facebook to recrawl the object to get the new image
            ping_url = "http://developers.facebook.com/tools/lint/?" + \
                urllib.urlencode({"url": url})
            client = tornado.httpclient.AsyncHTTPClient()
            client.fetch(ping_url, self.on_ping)

    def on_ping(self, response):
        if response.error:
            logging.error("Error refreshing Open Graph page: %r",
                          response.error)


class RecipeHandler(BaseHandler):
    @tornado.web.asynchronous
    def get(self, slug):
        if "facebookexternalhit" not in self.request.headers["User-Agent"] \
           and not self.current_user:
            self.redirect(self.get_login_url())
            return
        recipe = self.backend.get_recipe_by_slug(slug)
        if not recipe:
            raise tornado.web.HTTPError(404)
        self.render("recipe.html", recipe=recipe)


class CookbookHandler(BaseHandler):
    def get(self, id):
        user = self.backend.get_user(id)
        if not user:
            raise tornado.web.HTTPError(404)
        recipes = self.backend.get_recently_clipped_recipes([user["id"]])
        self.render("cookbook.html", user=user, recipes=recipes)


class CategoryHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        category = self.get_argument("name")
        recipes = self.backend.get_recently_clipped_recipes(
            [self.current_user.id], category=category)
        recipes.sort(key=lambda r: r["title"].lower())
        friend_recipes = self.backend.get_recently_clipped_recipes(
            self.backend.get_friend_ids(self.current_user), category=category,
            exclude_ids=[r["id"] for r in recipes])[:4]
        self.render("category.html", category=category, recipes=recipes,
                    friend_recipes=friend_recipes)


class EditHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        id = self.get_argument("id", None)
        recipe = self.backend.get_recipe(int(id)) if id else None
        if recipe and recipe["author_id"] != self.current_user["id"]:
            raise tornado.web.HTTPError(403)
        categories = self.backend.get_categories(self.current_user)
        self.render("edit.html", recipe=recipe, categories=categories)

    @tornado.web.authenticated
    def post(self):
        id = self.get_argument("id", None)
        recipe = self.backend.get_recipe(int(id)) if id else None
        if recipe:
            created = False
            if recipe["author_id"] != self.current_user["id"]:
                raise tornado.web.HTTPError(403)
            self.backend.update_recipe(
                id=recipe["id"],
                title=self.get_argument("title"),
                category=self.get_argument("category"),
                description=self.get_argument("description"),
                instructions=self.get_argument("instructions", ""),
                ingredients=self.get_argument("ingredients", ""),
            )
        else:
            created = True
            id = self.backend.create_recipe(
                author=self.current_user,
                title=self.get_argument("title"),
                category=self.get_argument("category"),
                description=self.get_argument("description"),
                instructions=self.get_argument("instructions", ""),
                ingredients=self.get_argument("ingredients", ""),
            )
            self.backend.clip_recipe(user=self.current_user, recipe_id=id)
        recipe = self.backend.get_recipe(int(id))
        self.redirect(self.reverse_url("recipe", recipe["slug"]))
        if not options.silent and created:
            url = "http://" + self.request.host + \
                self.reverse_url("recipe", recipe["slug"])
            self.backend.save_open_graph_action(
                type="clip", recipe=url, user=self.current_user,
                callback=self.on_open_graph)

    def on_open_graph(self, response):
        if response.error:
            logging.error("Error publishing clip to open graph: %r",
                          response.error)


class ClipHandler(BaseHandler):
    @tornado.web.authenticated
    def post(self):
        recipe_id = int(self.get_argument("recipe"))
        recipe = self.backend.get_recipe(recipe_id)
        if not recipe:
            raise tornado.web.HTTPError(404)
        if not options.silent:
            self.backend.clip_recipe(self.current_user, recipe["id"])
        self.write_json({
            "html": self.ui.modules.ActivityItem(
                self.current_user, recipe, datetime.datetime.utcnow(),
                "clipped"),
        })
        url = "http://" + self.request.host + \
            self.reverse_url("recipe", recipe["slug"])
        if not options.silent:
            self.backend.save_open_graph_action(
                type="clip", recipe=url, user=self.current_user,
                callback=self.on_open_graph)

    def on_open_graph(self, response):
        if response.error:
            logging.error("Error publishing clip to open graph: %r",
                          response.error)


class CookHandler(BaseHandler):
    @tornado.web.authenticated
    def post(self):
        recipe_id = int(self.get_argument("recipe"))
        recipe = self.backend.get_recipe(recipe_id)
        if not recipe:
            raise tornado.web.HTTPError(404)
        if not options.silent:
            self.backend.cook_recipe(self.current_user, recipe["id"])
        self.write_json({
            "html": self.ui.modules.ActivityItem(
                self.current_user, recipe, datetime.datetime.utcnow(),
                "cooked"),
        })
        url = "http://" + self.request.host + \
            self.reverse_url("recipe", recipe["slug"])
        if not options.silent:
            self.backend.save_open_graph_action(
                type="cook", recipe=url, user=self.current_user,
                callback=self.on_open_graph)

    def on_open_graph(self, response):
        if response.error:
            logging.error("Error publishing cook to open graph: %r (%r)",
                          response.error, response.body)


class LoginHandler(BaseHandler):
    @tornado.web.asynchronous
    def get(self):
        next = self.get_argument("next", None)
        code = self.get_argument("code", None)
        if not next:
            self.redirect(self.get_login_url(self.reverse_url("home")))
            return
        if not next.startswith("https://" + self.request.host + "/") and \
           not next.startswith("http://" + self.request.host + "/"):
            raise tornado.web.HTTPError(
                404, "Login redirect (%s) spans hosts", next)
        if self.get_argument("error", None):
            logging.warning("Facebook login error: %r", self.request.arguments)
            self.set_error_message(
                "An error occured with Facebook. Please try again later.")
            self.redirect(self.reverse_url("home"))
            return
        if not code:
            self.redirect(self.get_login_url(next))
            return
        redirect_uri = self.request.protocol + "://" + self.request.host + \
            self.request.path + "?" + urllib.urlencode({"next": next})
        url = "https://graph.facebook.com/oauth/access_token?" + \
            urllib.urlencode({
                "client_id": options.facebook_app_id,
                "client_secret": options.facebook_app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            })
        client = tornado.httpclient.AsyncHTTPClient()
        client.fetch(url, self.on_access_token)

    def on_access_token(self, response):
        if response.error:
            self.set_error_message(
                "An error occured with Facebook. Please try again later.")
            self.redirect(self.reverse_url("home"))
            return
        access_token = urlparse.parse_qs(response.body)["access_token"][-1]
        url = "https://graph.facebook.com/me?" + urllib.urlencode({
            "access_token": access_token,
        })
        client = tornado.httpclient.AsyncHTTPClient()
        client.fetch(url, functools.partial(self.on_profile, access_token))

    def on_profile(self, access_token, response):
        if response.error:
            self.set_error_message(
                "An error occured with Facebook. Please try again later.")
            self.redirect(self.reverse_url("home"))
            return
        profile = json.loads(response.body)
        url = "https://graph.facebook.com/me/friends?" + urllib.urlencode({
            "access_token": access_token,
        })
        client = tornado.httpclient.AsyncHTTPClient()
        client.fetch(url, functools.partial(
            self.on_friends, access_token, profile))

    def on_friends(self, access_token, profile, response):
        if response.error:
            self.set_error_message(
                "An error occured with Facebook. Please try again later.")
            self.redirect(self.reverse_url("home"))
            return
        friend_ids = [f["id"] for f in json.loads(response.body)["data"]]
        self.backend.create_user(profile, access_token)
        self.backend.update_friends(profile, friend_ids)
        self.set_secure_cookie("uid", profile["id"])
        self.redirect(self.get_argument("next", self.reverse_url("home")))


class Backend(object):
    def __init__(self):
        self.db = tornado.database.Connection(
            host=options.mysql_host, database=options.mysql_database,
            user=options.mysql_user, password=options.mysql_password)
        self.s3 = aws.S3Client(options.aws_s3_bucket)

    @classmethod
    def instance(cls):
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance

    def save_open_graph_action(self, user, type, callback, **properties):
        url = "https://graph.facebook.com/me/" + options.facebook_canvas_id + \
            ":" + type
        properties.update({
            "access_token": user["access_token"],
        })
        client = tornado.httpclient.AsyncHTTPClient()
        client.fetch(url, method="POST", body=urllib.urlencode(properties),
                     callback=callback)

    def get_user(self, id):
        return self.get_users([id]).get(id)

    def get_users(self, ids):
        if not ids:
            return {}
        users = self.db.query(
            "SELECT * FROM cookbook_users WHERE id IN (" +
            ",".join(["%s"] * len(ids)) + ")", *ids)
        for user in users:
            user["picture"] = "http://graph.facebook.com/" + user["id"] + \
                "/picture"
        return dict((a["id"], a) for a in users)

    def create_user(self, profile, access_token):
        self.db.execute(
            "INSERT IGNORE INTO cookbook_users (id,name,link,gender,"
            "access_token,created) VALUES (%s,%s,%s,%s,%s,UTC_TIMESTAMP) "
            "ON DUPLICATE KEY UPDATE name=%s, link=%s, gender=%s, "
            "access_token = %s",
            profile["id"], profile["name"], profile["link"], profile["gender"],
            access_token, profile["name"], profile["link"], profile["gender"],
            access_token)

    def update_friends(self, user, friend_ids):
        if not friend_ids:
            return
        friend_ids = [r["id"] for r in self.db.query(
            "SELECT * FROM cookbook_users WHERE id IN (" +
            ",".join(["%s"] * len(friend_ids)) + ")", *friend_ids)]
        if not friend_ids:
            return
        rows = [(user["id"], fid) for fid in friend_ids]
        rows += [(fid, user["id"]) for fid in friend_ids]
        self.db.executemany(
            "INSERT IGNORE INTO cookbook_friends (user_id, friend_id) "
            "VALUES (%s,%s)", rows)

    def get_friend_ids(self, user):
        return [r["friend_id"] for r in self.db.query(
            "SELECT friend_id FROM cookbook_friends WHERE user_id = %s",
            user["id"])]

    def get_recipe(self, id):
        return self.get_recipes([id]).get(id)

    def get_recipe_by_slug(self, slug):
        recipe = self.db.get(
            "SELECT * FROM cookbook_recipes WHERE slug = %s", slug)
        if not recipe:
            return None
        self._fill_recipes([recipe])
        return recipe

    def create_recipe(self, title, category, description, ingredients,
                      instructions, author):
        slug_base = title.replace(" ", "-").lower()
        valid_letters = string.ascii_letters + string.digits + "-"
        slug_base = "".join(c for c in slug_base if c in valid_letters)[:90]
        tries = 0
        while True:
            try:
                slug = slug_base + "-" + str(tries) if tries > 0 else slug_base
                return self.db.execute(
                    "INSERT INTO cookbook_recipes (title,category,description,"
                    "ingredients,instructions,author_id,slug,created) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP)", title, category,
                    description, ingredients, instructions, author["id"], slug)
            except tornado.database.IntegrityError:
                tries += 1

    def update_recipe(self, id, title, category, description, ingredients,
                      instructions):
        return self.db.execute(
            "UPDATE cookbook_recipes SET title = %s, category = %s, "
            "description = %s, ingredients = %s, instructions = %s "
            "WHERE id = %s", title, category, description, ingredients,
            instructions, id)

    def clip_recipe(self, user, recipe_id):
        self.db.execute(
            "INSERT IGNORE INTO cookbook_clipped (user_id, recipe_id) "
            "VALUES (%s,%s)", user["id"], recipe_id)

    def cook_recipe(self, user, recipe_id):
        self.db.execute(
            "INSERT IGNORE INTO cookbook_cooked (user_id, recipe_id) "
            "VALUES (%s,%s)", user["id"], recipe_id)

    def get_clipped_recipes(self, user):
        recipe_ids = [row["recipe_id"] for row in self.db.query(
            "SELECT recipe_id FROM cookbook_clipped WHERE user_id = %s",
            user["id"])]
        return self.get_recipes(recipe_ids).values()

    def save_photos(self, recipe, full, thumb):
        self.db.execute(
            "REPLACE INTO cookbook_photos (recipe_id,full_hash,full_width,"
            "full_height,thumb_hash,thumb_width,thumb_height) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s)", recipe["id"], full["hash"],
            full["width"], full["height"], thumb["hash"], thumb["width"],
            thumb["height"])

    def get_recently_clipped_recipes(self, user_ids, num=None,
                                     exclude_ids=None, category=None):
        if not user_ids:
            return []
        query = "SELECT DISTINCT recipe_id FROM cookbook_clipped WHERE " \
            "user_id IN (" + ",".join(["%s"] * len(user_ids)) + ")"
        args = list(user_ids)
        if exclude_ids:
            query += " AND recipe_id NOT IN (" + \
                ",".join(["%s"] * len(exclude_ids)) + ")"
            args += exclude_ids
        query += " ORDER BY created DESC"
        if num is not None:
            query += " LIMIT " + str(num)
        recipe_ids = [row["recipe_id"] for row in self.db.query(query, *args)]
        recipe_map = self.get_recipes(recipe_ids)
        if category:
            return [recipe_map[id] for id in recipe_ids
                    if recipe_map[id]["category"] == category]
        else:
            return [recipe_map[id] for id in recipe_ids]

    def get_recently_cooked_recipes(self, user, num):
        recipe_ids = [row["recipe_id"] for row in self.db.query(
            "SELECT recipe_id FROM cookbook_cooked WHERE user_id = %s "
            "ORDER BY created DESC LIMIT " + str(num), user["id"])]
        recipe_map = self.get_recipes(recipe_ids)
        return [recipe_map[id] for id in recipe_ids]

    def get_friend_activity(self, user, num):
        friend_ids = self.get_friend_ids(user) + [user["id"]]
        activity = self._make_activity("cooked", self.db.query(
            "SELECT user_id, recipe_id, created FROM cookbook_cooked WHERE "
            "user_id IN (" + ",".join(["%s"] * len(friend_ids)) + ") ORDER BY "
            "created DESC LIMIT " + str(num), *friend_ids))
        activity += self._make_activity("clipped", self.db.query(
            "SELECT user_id, recipe_id, created FROM cookbook_clipped WHERE "
            "user_id IN (" + ",".join(["%s"] * len(friend_ids)) + ") ORDER BY "
            "created DESC LIMIT " + str(num), *friend_ids))
        activity.sort(key=lambda a: a["created"], reverse=True)
        activity = activity[:num]
        users = self.get_users(set(a["user_id"] for a in activity))
        recipes = self.get_recipes(set(a["recipe_id"] for a in activity))
        for item in activity:
            item["user"] = users[item["user_id"]]
            item["recipe"] = recipes[item["recipe_id"]]
        return activity

    def get_recipes(self, ids):
        if not ids:
            return {}
        recipes = dict((r["id"], r) for r in self.db.query(
            "SELECT * FROM cookbook_recipes WHERE id IN (" +
            ",".join(["%s"] * len(ids)) + ")", *ids))
        self._fill_recipes(recipes.values())
        return recipes

    def get_categories(self, user):
        friend_ids = self.get_friend_ids(user) + [user["id"]]
        recipe_ids = [r["recipe_id"] for r in self.db.query(
            "SELECT DISTINCT recipe_id FROM cookbook_clipped WHERE "
            "user_id IN (" + ",".join(["%s"] * len(friend_ids)) + ")",
            *friend_ids)]
        if not recipe_ids:
            return []
        categories = [r["category"] for r in self.db.query(
            "SELECT DISTINCT category FROM cookbook_recipes WHERE id "
            "IN (" + ",".join(["%s"] * len(recipe_ids)) + ")", *recipe_ids)]
        categories.sort(key=lambda c: c.lower())
        return categories

    def recipe_is_clipped(self, user, recipe):
        return self.db.get(
            "SELECT recipe_id FROM cookbook_clipped WHERE user_id = %s AND "
            "recipe_id = %s", user["id"], recipe["id"]) is not None

    def get_friends_who_clipped(self, user, recipe):
        all_friends = self.get_friend_ids(user)
        if not all_friends:
            return []
        friend_ids = [r["user_id"] for r in self.db.query(
            "SELECT user_id FROM cookbook_clipped WHERE recipe_id = %s AND "
            "user_id IN (" + ",".join(["%s"] * len(all_friends)) + ") "
            "ORDER BY created DESC", recipe["id"], *all_friends)]
        friends = self.get_users(friend_ids)
        return [friends[fid] for fid in friend_ids]

    def get_clip_count(self, recipe):
        return self.db.get(
            "SELECT COUNT(*) AS num FROM cookbook_clipped WHERE "
            "recipe_id = %s", recipe["id"]).num

    def get_cook_count(self, recipe):
        return self.db.get(
            "SELECT COUNT(*) AS num FROM cookbook_cooked WHERE "
            "recipe_id = %s", recipe["id"]).num

    def get_recipe_photos(self, recipe_ids):
        if not recipe_ids:
            return {}
        photos = {}
        for row in self.db.query(
            "SELECT * FROM cookbook_photos WHERE recipe_id IN (" +
            ",".join(["%s"] * len(recipe_ids)) + ")", *recipe_ids):
            photos[row["recipe_id"]] = {
                "full": {
                    "hash": row["full_hash"],
                    "url": cdn_url(row["full_hash"]),
                    "width": row["full_width"],
                    "height": row["full_height"],
                },
                "thumb": {
                    "hash": row["thumb_hash"],
                    "url": cdn_url(row["thumb_hash"]),
                    "width": row["thumb_width"],
                    "height": row["thumb_height"],
                },
            }
        return photos

    def _fill_recipes(self, recipes):
        author_ids = set(r["author_id"] for r in recipes)
        recipe_ids = set(r["id"] for r in recipes)
        authors = self.get_users(author_ids)
        photos = self.get_recipe_photos(recipe_ids)
        for recipe in recipes:
            recipe["author"] = authors[recipe["author_id"]]
            recipe["photo"] = photos.get(recipe["id"])

    def _make_activity(self, action, rows):
        for row in rows:
            row["action"] = action
        return rows


class RecipeList(tornado.web.UIModule):
    def render(self, recipes):
        categories = {}
        for recipe in recipes:
            categories.setdefault(recipe["category"], []).append(recipe)
            for recipes in categories.itervalues():
                recipes.sort(key=lambda r: r["title"].lower())
        return self.render_string("recipe-list.html", categories=categories)


class Facepile(tornado.web.UIModule):
    def render(self, friends, num=7):
        return self.render_string("facepile.html", friends=friends, num=num)


class RecipeClips(tornado.web.UIModule):
    def render(self, recipes):
        return self.render_string("recipe-clips.html", recipes=recipes)


class ActivityStream(tornado.web.UIModule):
    def render(self, num=10):
        if not self.current_user:
            return ""
        activity = self.handler.backend.get_friend_activity(
            self.current_user, num=num)
        if not activity:
            return ""
        return self.render_string("activity-stream.html", activity=activity)


class ActivityItem(tornado.web.UIModule):
    def render(self, user, recipe, date, action):
        return self.render_string(
            "activity-item.html", user=user, recipe=recipe, date=date,
            action=action)


class RecipePhoto(tornado.web.UIModule):
    def render(self, recipe, width, max_height=None, height=None, href=None):
        if not recipe["photo"]:
            if not height:
                height = max_height
            return self.render_string(
                "recipe-photo-upload.html", recipe=recipe, width=width,
                height=height)
        thumb = recipe["photo"]["thumb"]
        if max_height:
            ratio = width / (1.0 * thumb["width"])
            visible_height = min(int(ratio * thumb["height"]), max_height)
        else:
            ratio = max(height / (1.0 * thumb["height"]),
                        width / (1.0 * thumb["width"]))
            visible_height = height
        real_width = int(ratio * thumb["width"])
        real_height = int(ratio * thumb["height"])
        offset_x = (width - real_width) / 2
        offset_y = (visible_height - real_height) / 2
        return self.render_string(
            "recipe-photo.html", recipe=recipe, href=href,
            real_width=real_width, real_height=real_height, offset_x=offset_x,
            offset_y=offset_y, width=width, height=visible_height)


class RecipeActions(tornado.web.UIModule):
    def render(self, recipe):
        clipped = self.handler.backend.recipe_is_clipped(
            self.current_user, recipe)
        return self.render_string(
            "recipe-actions.html", recipe=recipe, clipped=clipped)


class RecipeInfo(tornado.web.UIModule):
    def render(self, recipe):
        cook_count = self.handler.backend.get_cook_count(recipe)
        clip_count = self.handler.backend.get_clip_count(recipe)
        return self.render_string(
            "recipe-info.html", recipe=recipe, cook_count=cook_count,
            clip_count=clip_count)


class RecipeContext(tornado.web.UIModule):
    def render(self, recipe, facepile_size=5, friend_list_size=3):
        friends = self.handler.backend.get_friends_who_clipped(
            self.current_user, recipe)
        if not friends:
            return ""
        clipped = self.handler.backend.recipe_is_clipped(
            self.current_user, recipe)
        return self.render_string(
            "recipe-context.html", recipe=recipe, friends=friends,
            clipped=clipped, friend_list_size=friend_list_size,
            facepile_size=facepile_size)


def cdn_url(hash):
    return "http://" + options.aws_cloudfront_host + "/" + hash


def main():
    tornado.options.parse_command_line()
    if options.config:
        tornado.options.parse_config_file(options.config)
    else:
        path = os.path.join(os.path.dirname(__file__), "settings.py")
        tornado.options.parse_config_file(path)
    CookbookApplication().listen(options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()
