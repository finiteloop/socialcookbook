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

import base64
import email.utils
import hashlib
import hmac
import mimetypes
import re
import time
import tornado.httpclient
import urllib

from tornado.options import define, options

define("aws_access_key_id")
define("aws_secret_access_key")


class S3Client(object):
    def __init__(self, bucket, access_key_id=None, secret_access_key=None):
        self.bucket = bucket
        if access_key_id is not None:
            self.access_key_id = access_key_id
            self.secret_access_key = secret_access_key
        else:
            self.access_key_id = options.aws_access_key_id
            self.secret_access_key = options.aws_secret_access_key
        if isinstance(self.secret_access_key, unicode):
            self.secret_access_key = self.secret_access_key.encode("utf-8")
        self.host = "http://" + bucket + ".s3.amazonaws.com"

    def put_object(self, key, body, callback, headers={}):
        headers = self._default_headers(headers)
        headers["Content-Length"] = len(body)
        if self.access_key_id:
            headers["Authorization"] = self._auth_header("PUT", key, headers)
        http = tornado.httpclient.AsyncHTTPClient()
        http.fetch(self.host + "/" + key, method="PUT", headers=headers,
                   body=body, callback=callback)

    def put_cdn_content(self, data, callback, file_name=None, mime_type=None):
        """Uploads the given data as an object optimized for CloudFront.

        The object name is the hash of the mime type and file contents,
        so every unique file is represented exactly once in the CDN. We
        set the HTTP headers on the object to be optimized for public CDN
        consumption, including an infinite expiration time (since the file
        is named by its contents, it is guaranteed not to change) and the
        appropriate public Amazon ACL.

        If file_name is given, we include that in the object as a
        Content-Disposition header, so if a user saves the file, it will
        have a friendlier name upon download. If given, we also infer
        the mime type from the file name.

        We return the hash we used as the object name.
        """
        # Infer the mime type and extension if not given
        if not mime_type and file_name:
            mime_type, encoding = mimetypes.guess_type(file_name)
        if not mime_type:
            mime_type = "application/unknown"
        if isinstance(mime_type, unicode):
            mime_type = mime_type.encode("utf-8")

        # Cache the file forever, and inlcude the mime type in the file hash
        # since the Content-Type header will change the way the browser renders
        headers = {
            "Content-Type": mime_type,
            "Expires": email.utils.formatdate(time.time() + 86400 * 365 * 10),
            "Cache-Control": "public, max-age=" + str(86400 * 365 * 10),
            "Vary": "Accept-Encoding",
            "x-amz-acl": "public-read",
        }
        file_hash = hashlib.sha1(mime_type + "|" + data).hexdigest()

        # Retain the file name for friendly downloading
        if file_name:
            if file_name != re.sub(r"[\x00-\x1f]", " ", file_name)[:4000]:
                raise Exception("Unsafe file name %r" % file_name)
            file_name = file_name.split("/")[-1]
            file_name = file_name.split("\\")[-1]
            file_name = file_name.replace('"', '').strip()
            if isinstance(file_name, unicode):
                file_name = file_name.encode("utf-8")
        if file_name:
            headers["Content-Disposition"] = \
                'inline; filename="%s"' % file_name

        def on_put(response):
            if response.error:
                logging.error("Amazon S3 error: %r", response)
                callback(None)
            else:
                callback(file_hash)
        self.put_object(file_hash, data, callback=on_put, headers=headers)

    def _default_headers(self, custom={}):
        headers = {
            "Date": email.utils.formatdate(time.time())
        }
        headers.update(custom)
        return headers

    def _auth_header(self, method, key, headers):
        special_headers = ("content-md5", "content-type", "date")
        signed_headers = dict((k, "") for k in special_headers)
        signed_headers.update(
            (k.lower(), v) for k, v in headers.items()
            if k.lower().startswith("x-amz-") or k.lower() in special_headers)
        sorted_header_keys = list(sorted(signed_headers.keys()))

        buffer = "%s\n" % method
        for header_key in sorted_header_keys:
            if header_key.startswith("x-amz-"):
                buffer += "%s:%s\n" % (header_key, signed_headers[header_key])
            else:
                buffer += "%s\n" % signed_headers[header_key]
        buffer += "/%s" % self.bucket + "/%s" % urllib.quote_plus(key)
        
        signature = hmac.new(self.secret_access_key, buffer, hashlib.sha1)
        return "AWS " + self.access_key_id + ":" + \
            base64.encodestring(signature.digest()).strip()
