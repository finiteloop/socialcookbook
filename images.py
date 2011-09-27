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

"""An image resizing library based on ImageMagick and ctypes"""

import binascii
import ctypes
import ctypes.util


def get_image_info(data):
    """Returns the width, height, and MIME type of the given image as a dict"""
    return _ImageMagick.instance().get_image_info(data)


def resize_image(data, max_width, max_height, quality=85, crop=False,
                 force=False):
    """Resizes the given image to the given specifications.

    We size down the image to the given maximum width and height. Unless force
    is True, we don't resize an image smaller than the given width and height.

    We use the JPEG format for any image that has to be resized. If the image
    does not have to be resized, we retain the original image format.

    If crop is True, we resize the image so that at least one of the width or
    height is within the given bounds, and then we crop the other dimension.

    We use the given JPEG quality in the cases where we use the JPEG format.
    We always convert to JPEG for image formats other than PNG and GIF.

    We return a dict with the keys "data", "mime_type", "width", and "height".
    """
    return _ImageMagick.instance().resize_image(
        data=data, max_width=max_width, max_height=max_height, quality=quality,
        crop=crop, force=force)


class ImageException(Exception):
    """An exception related to the ImageMagick library"""
    pass


class _ImageMagick(object):
    def __init__(self):
        wand_path = ctypes.util.find_library("MagickWand")
        if not wand_path:
            raise Exception("Package libmagick9 or libmagick10 required")
        self.lib = ctypes.CDLL(wand_path)
        method = self.lib.MagickResizeImage
        method.restype = ctypes.c_int
        method.argtypes = (ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_int, ctypes.c_double)
        self.pixel_wand = self.lib.NewPixelWand()
        self.lib.PixelSetColor(self.pixel_wand, "#ffffff")

    @classmethod
    def instance(cls):
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance

    def get_image_info(self, data):
        wand = self.lib.NewMagickWand()
        try:
            if not self.lib.MagickReadImageBlob(wand, data, len(data)):
                raise ImageException("Unsupported image format; data: %s...",
                                     binascii.b2a_hex(data[:32]))
            ptr = self.lib.MagickGetImageFormat(wand)
            format = ctypes.string_at(ptr).upper()
            self.lib.MagickRelinquishMemory(ptr)
            return {
                "mime_type": "image/" + format.lower(),
                "width": self.lib.MagickGetImageWidth(wand),
                "height": self.lib.MagickGetImageHeight(wand),
            }
        finally:
            self.lib.DestroyMagickWand(wand)

    def resize_image(self, data, max_width, max_height, quality=85,
                     crop=False, force=False):
        wand = self.lib.NewMagickWand()
        try:
            if not self.lib.MagickReadImageBlob(wand, data, len(data)):
                raise ImageException("Unsupported image format; data: %s...",
                                     binascii.b2a_hex(data[:32]))
            width = self.lib.MagickGetImageWidth(wand)
            height = self.lib.MagickGetImageHeight(wand)
            self.lib.MagickStripImage(wand)
            if crop:
                ratio = max(max_height * 1.0 / height, max_width * 1.0 / width)
            else:
                ratio = min(max_height * 1.0 / height, max_width * 1.0 / width)

            ptr = self.lib.MagickGetImageFormat(wand)
            src_format = ctypes.string_at(ptr).upper()
            self.lib.MagickRelinquishMemory(ptr)
            format = src_format

            if ratio < 1.0 or force:
                format = "JPEG"
                self.lib.MagickResizeImage(
                    wand, int(ratio * width + 0.5), int(ratio * height + 0.5),
                    0, 1.0)
            elif format not in ("GIF", "JPEG", "PNG"):
                format = "JPEG"

            if format != src_format:
                # Flatten to fix background on transparent images. We have to
                # do this before cropping, as MagickFlattenImages appears to
                # drop all the crop info from that step
                self.lib.MagickSetImageBackgroundColor(wand, self.pixel_wand) 
                flat_wand = self.lib.MagickFlattenImages(wand)
                self.lib.DestroyMagickWand(wand)
                wand = flat_wand

            if crop:
                x = (self.lib.MagickGetImageWidth(wand) - max_width) / 2
                y = (self.lib.MagickGetImageHeight(wand) - max_height) / 2
                self.lib.MagickCropImage(wand, max_width, max_height, x, y)

            if format == "JPEG":
                # Default compression is best for PNG, GIF.
                self.lib.MagickSetCompressionQuality(wand, quality)

            self.lib.MagickSetFormat(wand, format)
            size = ctypes.c_size_t()
            ptr = self.lib.MagickGetImageBlob(wand, ctypes.byref(size))
            body = ctypes.string_at(ptr, size.value)
            self.lib.MagickRelinquishMemory(ptr)

            return {
                "data": body,
                "mime_type": "image/" + format.lower(),
                "width": self.lib.MagickGetImageWidth(wand),
                "height": self.lib.MagickGetImageHeight(wand),
            }
        finally:
            self.lib.DestroyMagickWand(wand)
