#!/usr/bin/env python3

import itertools as it, operator as op, functools as ft
from collections import deque
from pathlib import Path
import os, sys, logging

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib


class LogMessage:
	def __init__(self, fmt, a, k): self.fmt, self.a, self.k = fmt, a, k
	def __str__(self): return self.fmt.format(*self.a, **self.k) if self.a or self.k else self.fmt

class LogStyleAdapter(logging.LoggerAdapter):
	def __init__(self, logger, extra=None):
		super(LogStyleAdapter, self).__init__(logger, extra or {})
	def log(self, level, msg, *args, **kws):
		if not self.isEnabledFor(level): return
		log_kws = {} if 'exc_info' not in kws else dict(exc_info=kws.pop('exc_info'))
		msg, kws = self.process(msg, kws)
		self.logger._log(level, LogMessage(msg, args, kws), (), log_kws)

get_logger = lambda name: LogStyleAdapter(logging.getLogger(name))


class ScrollerWindow(Gtk.ApplicationWindow):

	vbox_spacing = 3
	scroll_delay = 0.3
	queue_size = 3
	queue_preload_at = 0.7

	def _set_visual(self, w, *ev_data):
		visual = w.get_screen().get_rgba_visual()
		if visual: w.set_visual(visual)

	def _place_window(self, w, *ev_data):
		w.resize(800, 500)

	def __init__(self, app, src_paths_iter, auto_scroll):
		super(ScrollerWindow, self).__init__(name='scroller', application=app)
		self.src_paths_iter, self.auto_scroll = src_paths_iter, auto_scroll
		self.box_images = deque()
		self.log = get_logger('win')

		self.init_widgets()
		self.init_content()


	def init_widgets(self):
		# css = Gtk.CssProvider()
		# css.load_from_data('\n'.join([
		# 	'#notification { background: transparent; }' ]).encode())
		# Gtk.StyleContext.add_provider_for_screen(
		# 	Gdk.Screen.get_default(), css,
		# 	Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION )

		self.connect('composited-changed', self._set_visual)
		self.connect('screen-changed', self._set_visual)
		self._set_visual(self)

		self.scroll = Gtk.ScrolledWindow()
		self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.ALWAYS)
		self.add(self.scroll)
		self.box = Gtk.VBox(spacing=self.vbox_spacing, expand=True)
		self.scroll.add_with_viewport(self.box)

		self.scroll_ev = None
		self.scroll.get_vadjustment().connect('value-changed', self._scroll_ev)

		self.connect('show', self._place_window)
		self.connect('configure-event', self._place_window)


	def init_content(self):
		for n in range(self.queue_size): self._show_next_image()
		if self.auto_scroll:
			px, s = self.auto_scroll
			adj = self.scroll.get_vadjustment()
			GLib.timeout_add( s * 1000,
				ft.partial(self._scroll_ev_adjust, adj, offset=px, repeat=True) )


	def _scroll_ev(self, adj):
		if self.scroll_ev:
			GLib.source_remove(self.scroll_ev)
			self.scroll_ev = None
		self.scroll_ev = GLib.timeout_add(
			self.scroll_delay * 1000, self._scroll_ev_adjust, adj )

	def _scroll_ev_adjust(self, adj, offset=None, repeat=False):
		self.scroll_ev = None
		pos = adj.get_value()
		pos_max = self.box.get_allocated_height() - self.get_size()[1]
		if offset:
			pos = pos + offset
			adj.set_value(pos)
		if pos >= pos_max * self.queue_preload_at:
			h_offset = self._show_next_image()
			adj.set_value(pos - h_offset)
		return repeat


	def _show_next_image(self):
		p = next(self.src_paths_iter)
		if not p: return 0

		image = self._add_image(p)
		self.box.add(image)
		self.box_images.append(image)
		image.show()

		h_offset = 0
		while len(self.box_images) > self.queue_size:
			image = self.box_images.popleft()
			h_offset += image.get_allocation().height
			image.destroy()
		return h_offset


	def _add_image(self, path):
		self.log.debug('Adding image: {}', path)
		pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
		image = Gtk.Image()
		image.w_chk = None
		self.connect('check_resize', self._update_image, pixbuf, image)
		return image

	def _update_image(self, w, pixbuf, image):
		alloc = self.box.get_allocation()
		if image.w_chk == alloc.width: return
		image.w_chk = alloc.width
		# log.debug('Resizing image')
		# image.set_allocation(alloc)
		aspect = pixbuf.get_width() / pixbuf.get_height()
		w, h = alloc.width, int(alloc.width / aspect)
		pixbuf_resized = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
		image.set_from_pixbuf(pixbuf_resized)


class ScrollerApp(Gtk.Application):

	def __init__(self, *win_args, **win_kws):
		self.win_opts = win_args, win_kws
		super(ScrollerApp, self).__init__()

	def do_activate(self):
		win = ScrollerWindow(self, *self.win_opts[0], **self.win_opts[1])
		win.connect('delete-event', lambda w,*data: self.quit())
		win.show_all()


def file_iter(src_paths):
	'Infinite iter for image paths.'
	for path in map(Path, src_paths):
		if not path.exists():
			log.warn('Path does not exists: {}', path)
			continue
		if path.is_dir():
			for root, dirs, files in os.walk(str(path)):
				root = Path(root)
				for fn in files: yield str(root / fn)
		else: yield str(path)
	while True: yield

def main(args=None):
	import argparse
	parser = argparse.ArgumentParser(
		description='Display image-scroller window.')

	parser.add_argument('image_path', nargs='*',
		help='Path to file(s) or directories (will be searched recursively) to display images from.'
			' All found files will be treated as images,'
				' use e.g. find/grep/xargs for filename-based filtering.'
			' If no paths are provided, current'
				' directory is used by default. See also --file-list option.')
	parser.add_argument('-f', '--file-list', metavar='path',
		help='File with a list of image files/dirs paths to use, separated by newlines.'
			' Can be a fifo or pipe, use "-" to read it from stdin.')

	parser.add_argument('-a', '--auto-scroll', metavar='px[:interval]',
		help='Auto-scroll by specified number of pixels with specified interval (1s by defaul).')

	parser.add_argument('-d', '--debug', action='store_true', help='Verbose operation mode.')
	opts = parser.parse_args(sys.argv[1:] if args is None else args)

	global log
	import logging
	logging.basicConfig(
		format='%(asctime)s :: %(levelname)s :: %(message)s',
		datefmt='%Y-%m-%d %H:%M:%S',
		level=logging.DEBUG if opts.debug else logging.WARNING )
	log = get_logger('main')

	src_paths = opts.image_path or list()
	if opts.file_list:
		if src_paths: parser.error('Either --file-list or image_path args can be specified, not both.')
		src_file = Path(opts.file_list).open() if opts.file_list != '-' else sys.stdin
		src_paths = iter(lambda: src_file.readline().rstrip('\r\n').strip('\0'), '')
	elif not src_paths: src_paths.append('.')
	src_paths_iter = file_iter(src_paths)

	auto_scroll = opts.auto_scroll
	if auto_scroll:
		try: px, s = map(float, auto_scroll.split(':', 1))
		except ValueError: px, s = float(auto_scroll), 1
		auto_scroll = px, s

	log.debug('Starting application...')
	ScrollerApp(src_paths_iter, auto_scroll).run()

if __name__ == '__main__':
	import signal
	signal.signal(signal.SIGINT, signal.SIG_DFL)
	sys.exit(main())
