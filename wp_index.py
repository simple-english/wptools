#!/usr/bin/env python
"""
Index or split Wikipedia XML Dump into alphabetical (gz) files

This expects to operate on the (currently ~12GB)
latest/enwiki-latest-pages-articles.xml.bz2
The process is interruptable and restartable.

INPUT
   fname  XML Dump filename
          see -h for options

OUTPUT
   index or split (gzip) files to dest/[0-9], dest/[A-Z]

References
    https://en.wikipedia.org/wiki/Wikipedia:Database_download
    https://en.wikipedia.org/wiki/Wikipedia:Vital_articles/Expanded
    http://effbot.org/zone/celementtree.htm
"""

from __future__ import print_function

__author__ = "siznax"
__version__ = "1 Oct 2015"

import argparse
import bz2
import gzip
import os
import re
import sys
import string
import time
import traceback

DEFAULT_CHUNK_KB = 1
ONE_KB = 1000
ONE_MB = 1000**2
MAX_MEGABYTES = 1000 * 100  # 100 GB
REPORT_INTERVAL_MB = 10

from wp_parser import WPLineParser


class IndexParser(WPLineParser):

    def __init__(self, dest, offset, split):
        WPLineParser.__init__(self)
        self._files = dict()
        self._paths = dict()
        self.bytes_read = 0
        self.dest = dest
        self.first_title = ""
        self.first_title_start = 0
        self.offset = offset
        self.split = split
        self.tell = 0
        self.title = ""
        self.title_start = 0
        self.titles = None
        self.titles_found = []
        self.titles_written = 0

    def add_file(self, key):
        path = "%s/%s" % (self.dest, key)
        print("+ open %s" % path)
        self._files[key] = file(path, 'w')
        self._paths[key] = path

    def open_files(self, titles=False):
        if not self.dest:
            return
        os.mkdir(self.dest)
        for char in string.digits + string.ascii_uppercase + "_":
            path = "%s/%s" % (self.dest, char)
            print("+ open %s" % path)
            self._files[char] = gzip.open(path, 'wb')
            self._paths[char] = path
        if titles:
            self.add_file("titles_found")
            self.add_file("titles_left")

    def close_files(self):
        if not self.dest:
            return
        for key, handle in self._files.iteritems():
            tell = handle.tell()
            path = self._paths[key]
            handle.close()
            if tell:
                print("wrote %d bytes to %s" % (tell, path))

    def _write(self, title, title_start, elem):
        _file = self._files[ascii_bin(title)]
        if self.split:
            if self.titles:
                if title in self.titles:
                    _file.write(elem)
                    self.titles_written += 1
                    self.titles_found.append(title)
                    self.titles.remove(title)
            else:
                _file.write(elem)
        else:
            _file.write("%s %s\n" % (title, title_start))

    def process(self, elem):
        title = page_title(elem)
        title_start = self.offset + self.byte_count - len(elem)
        if not self.title:
            self.first_title = title
            self.first_title_start = title_start
        self.title = title
        self.title_start = title_start
        if not self.dest:
            # print("%s %s" % (title, len(elem)))
            return
        self._write(title, title_start, elem)


def page_title(page):
    """returns title from XML Dump <page>"""
    m = re.search(r"<title>([^<]*)<", page)
    if not m:
        print(page[:64])
        raise ValueError("title not found!")
    return m.group(1)


def ascii_bin(title):
    """returns first 0-9 or A-Z character in upper(title)"""
    try:
        return [x for x in title.upper()
                if 47 < ord(x) < 58 or 64 < ord(x) < 91][0]
    except:
        return "_"


def setup(dest, offset, split, titles):
    if dest and os.path.exists(dest):
        print("Destination exists: %s" % dest, file=sys.stderr)
        sys.exit(os.EX_IOERR)
    ip = IndexParser(dest, offset, split)
    ip.open_files(titles)
    if titles:
        with open(titles) as fh:
            ip.titles = set(fh.read().split("\n"))
            print("Pulling %d titles" % len(ip.titles))
    return ip


def gobble(ip, fname, chunk_size, max_mb, offset, report_mb):
    chunk_size = ONE_KB * chunk_size
    est_bytes_read = 0
    max_bytes = max_mb * ONE_MB
    report_bytes = report_mb * ONE_MB
    with bz2.BZ2File(fname, 'r') as zh:
        zh.seek(offset)
        try:
            while ip.bytes_read < max_bytes:
                # data = zh.read(chunk_size)  SLOOOW
                data = zh.readlines(chunk_size)
                if not data:
                    return
                ip.parse(data)
                ip.tell = zh.tell()
                ip.bytes_read = ip.tell - offset
                est_bytes_read += chunk_size
                if est_bytes_read % report_bytes == 0:
                    print("  %s %d" % (ip.title, ip.title_start))
                    sys.stdout.flush()
        except KeyboardInterrupt:
            teardown(ip)
            sys.exit(os.EX_SOFTWARE)
        except Exception:
            print("Exception at byte position: %d" % zh.tell())
            traceback.print_exc()


def teardown(ip):
    if ip.titles:
        ip._files['titles_found'].write("\n".join(sorted(ip.titles_found)))
        ip._files['titles_left'].write("\n".join(sorted(ip.titles)))
    ip.close_files()
    print("pages found: %d" % ip.elems_found)
    print("titles processed: %d" % ip.elems_processed)
    if ip.titles:
        print("titles written: %d" % ip.titles_written)
        print("titles leftover: %d" % len(ip.titles))
    print("first: %s %d" % (ip.first_title, ip.first_title_start))
    print("last: %s %d" % (ip.title, ip.title_start))
    print("read: %d MB" % (ip.bytes_read / ONE_MB))
    print("tell: %s" % ip.tell)


def _main(fname, max_mb, chunk_size, dest, offset, report_mb, split, titles):
    if titles:
        split = True
    if titles and not dest:
        print("-titles doesn't make sense without -dest")
        sys.exit(os.EX_USAGE)
    ip = setup(dest, offset, split, titles)
    gobble(ip, fname, chunk_size, max_mb, offset, report_mb)
    teardown(ip)


if __name__ == "__main__":
    desc = "Index or split Wikipedia XML Dump into alphabetical (gz) files"
    argp = argparse.ArgumentParser(description=desc)
    argp.add_argument("fname", help="XML Dump (bz2) filename")
    argp.add_argument("-c", "-chunksize", type=int, default=DEFAULT_CHUNK_KB,
                      help="chunk size in KB (default=%d)" % DEFAULT_CHUNK_KB)
    argp.add_argument("-d", "-dest", help="write results to dest (dir)")
    argp.add_argument("-m", "-maxbytes", type=int, default=MAX_MEGABYTES,
                      help="max bytes in MB (default=%d)" % MAX_MEGABYTES)
    argp.add_argument("-o", "-offset", type=int, default=0,
                      help="seek to byte offset")
    argp.add_argument("-r", "-report", type=int, default=REPORT_INTERVAL_MB,
                      help=("report interval in MB (default=%d)"
                            % REPORT_INTERVAL_MB))
    argp.add_argument("-s", "-split", action='store_true',
                      help="split (versus index) into files")
    argp.add_argument("-t", "-titles", help="flat file of titles to pull")
    args = argp.parse_args()

    start = time.time()
    _main(args.fname, args.m, args.c, args.d, args.o, args.r, args.s, args.t)
    print("%5.3f seconds" % (time.time() - start))