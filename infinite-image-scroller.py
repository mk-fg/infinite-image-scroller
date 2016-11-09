#!/usr/bin/env python3

import itertools as it, operator as op, functools as ft
from collections import deque
from pathlib import Path
import os, sys, re, logging

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


class ScrollerConf:

	app_id = 'net.fraggod.infinite-image-scroller'
	no_session = False

	win_title = 'infinite-image-scroller'
	win_role = 'scroller-main'
	win_icon = None
	win_default_size = 700, 500
	win_w = win_h = None
	win_x = win_y = None

	wm_hints = None
	wm_hints_all = (
		' focus_on_map modal resizable hide_titlebar_when_maximized'
		' stick maximize fullscreen keep_above keep_below decorated'
		' deletable skip_taskbar skip_pager urgency accept_focus'
		' auto_startup_notification mnemonics_visible focus_visible' ).split()
	wm_type_hints = Gdk.WindowTypeHint.NORMAL
	wm_type_hints_all = dict(
		(e.value_nick, v) for v, e in Gdk.WindowTypeHint.__enum_values__.items() if v )

	vbox_spacing = 3
	scroll_event_delay = 0.2
	queue_size = 3
	queue_preload_at = 0.7
	image_opacity = 1.0
	auto_scroll = None
	image_open_attempts = 3

	# Format is '[mod1 ...] key', with modifier keys alpha-sorted, see _window_key() func
	quit_keys = 'q', 'control q', 'control w', 'escape'

	def __init__(self, **kws):
		for k, v in kws.items():
			if not hasattr(self, k): raise AttributeError(k)
			setattr(self, k, v)


class ScrollerWindow(Gtk.ApplicationWindow):

	def __init__(self, app, src_paths_iter, conf):
		super(ScrollerWindow, self).__init__(name='infinite-image-scroller', application=app)
		self.app, self.src_paths_iter, self.conf = app, src_paths_iter, conf
		self.log = get_logger('win')

		self.set_title(self.conf.win_title)
		self.set_role(self.conf.win_role)
		if self.conf.win_icon:
			self.log.debug('Using icon: {}', self.conf.win_icon)
			self.set_icon_name(self.conf.win_icon)

		self.init_widgets()
		self.init_content()


	def init_widgets(self):
		css = Gtk.CssProvider()
		css.load_from_data('''
				@binding-set image-scroller-keys {
					bind "Up" { "scroll-child" (step-up, 0) };
					bind "Down" { "scroll-child" (step-down, 0) };
					bind "Left" { "scroll-child" (step-left, 1) };
					bind "Right" { "scroll-child" (step-right, 1) };
					bind "w" { "scroll-child" (step-up, 0) };
					bind "s" { "scroll-child" (step-down, 0) };
					bind "a" { "scroll-child" (step-left, 1) };
					bind "d" { "scroll-child" (step-right, 1) }; }
				#infinite-image-scroller scrolledwindow { -gtk-key-bindings: image-scroller-keys; }
				#infinite-image-scroller,
				#infinite-image-scroller * { background: transparent; }
			'''.encode())
		Gtk.StyleContext.add_provider_for_screen(
			Gdk.Screen.get_default(), css,
			Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION )

		self.scroll = Gtk.ScrolledWindow()
		self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.ALWAYS)
		self.add(self.scroll)
		self.box = Gtk.VBox(spacing=self.conf.vbox_spacing, expand=True)
		self.scroll.add_with_viewport(self.box)
		self.box_images = deque()

		self.scroll_ev = None
		self.scroll.get_vadjustment().connect('value-changed', self._scroll_ev)

		hints = dict.fromkeys(self.conf.wm_hints_all)
		hints.update(self.conf.wm_hints or dict())
		for k in list(hints):
			setter = getattr(self, 'set_{}'.format(k), None)
			if not setter: setter = getattr(self, 'set_{}_hint'.format(k), None)
			if not setter: setter = getattr(self, k, None)
			if not setter: continue
			v = hints.pop(k)
			if v is None: continue
			self.log.debug('Setting WM hint: {} = {}', k, v)
			if not setter.get_arguments(): # e.g. w.fullscreen()
				if v: setter()
				continue
			setter(v)
		assert not hints, ['Unrecognized wm-hints:', hints]
		self.set_type_hint(self.conf.wm_type_hints)

		self.connect('composited-changed', self._set_visual)
		self.connect('screen-changed', self._set_visual)
		self._set_visual(self)

		self.ev_discard = set()
		self.set_default_size(*self.conf.win_default_size)
		self.connect('show', self._place_window, 'show')
		self.connect( 'configure-event',
			ft.partial(self._place_window, ev_done='configure-event') )
		self._place_window(self)

		self.connect('key-press-event', self._window_key)


	def init_content(self):
		for n in range(self.conf.queue_size): self._show_next_image()
		if self.conf.auto_scroll:
			px, s = self.conf.auto_scroll
			adj = self.scroll.get_vadjustment()
			GLib.timeout_add( s * 1000,
				ft.partial(self._scroll_ev_adjust, adj, offset=px, repeat=True) )


	def _set_visual(self, w, *ev_data):
		visual = w.get_screen().get_rgba_visual()
		if visual: w.set_visual(visual)

	def _place_window(self, w, *ev_data, ev_done=None):
		if ev_done:
			if ev_done in self.ev_discard: return
			self.ev_discard.add(ev_done)
		s = w.get_screen()
		sw, sh = s.width(), s.height()
		ww = wh = None
		if self.conf.win_w and self.conf.win_h:
			get_val = lambda v,sv: int(v) if v != 'S' else sv
			ww, wh = get_val(self.conf.win_w, sw), get_val(self.conf.win_h, sh)
			w.resize(ww, wh)
		if self.conf.win_x or self.conf.win_y:
			if not (ww or wh): ww, wh = w.get_size()
			wx, wy = w.get_position()
			get_pos = lambda v,sv,wv: int(v[1]) if v[0] != '-' else (sv - wv + int(v[1]))
			if self.conf.win_x: w.move(get_pos(self.conf.win_x, sw, ww), wy)
			if self.conf.win_y: w.move(wx, get_pos(self.conf.win_y, sh, wh))

	def _window_key(self, w, ev, _masks=dict()):
		if not _masks:
			for st, mod in Gdk.ModifierType.__flags_values__.items():
				if ( len(mod.value_names) != 1
					or not mod.first_value_nick.endswith('-mask') ): continue
				assert st not in _masks, [mod.first_value_nick, _masks[st]]
				mod = mod.first_value_nick[:-5]
				if mod.startswith('modifier-reserved-'): mod = 'res-{}'.format(mod[18:])
				_masks[st] = mod
		chk, keyval = ev.get_keyval()
		if not chk: return
		key_sum, key_name = list(), Gdk.keyval_name(keyval)
		for st, mod in _masks.items():
			if ev.state & st == st: key_sum.append(mod)
		key_sum = ' '.join(sorted(key_sum) + [key_name]).lower()
		self.log.debug('key-press-event: {!r}', key_sum)
		if key_sum in self.conf.quit_keys: self.app.quit()


	def _scroll_ev(self, adj):
		if self.scroll_ev:
			GLib.source_remove(self.scroll_ev)
			self.scroll_ev = None
		self.scroll_ev = GLib.timeout_add(
			self.conf.scroll_event_delay * 1000, self._scroll_ev_adjust, adj )

	def _scroll_ev_adjust(self, adj, offset=None, repeat=False):
		self.scroll_ev = None
		pos = adj.get_value()
		pos_max = self.box.get_allocated_height() - self.get_size()[1]
		if offset:
			pos = pos + offset
			adj.set_value(pos)
		if pos >= pos_max * self.conf.queue_preload_at:
			h_offset = self._show_next_image() + self.conf.vbox_spacing
			adj.set_value(pos - h_offset)
		return repeat


	def _show_next_image(self):

		for n in range(self.conf.image_open_attempts):
			p = next(self.src_paths_iter)
			if not p: return 0
			image = self._add_image(p)
			if image: break
		else:
			self.log.error( 'Failed to get new image'
				' in {} attempt(s), giving up', self.conf.image_open_attempts )
			return 0
		self.box.add(image)
		self.box_images.append(image)
		image.show()

		h_offset = 0
		while len(self.box_images) > self.conf.queue_size:
			image = self.box_images.popleft()
			h_offset += image.get_allocation().height
			image.destroy()
		return h_offset


	def _add_image(self, path):
		self.log.debug('Adding image: {}', path)
		try: pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
		except Exception as err:
			self.log.error( 'Failed to create gdk-pixbuf'
				' from file: [{}] {}', err.__class__.__name__, err )
			return
		image = Gtk.Image()
		image.w_chk = None
		if self.conf.image_opacity < 1.0:
			image.set_opacity(self.conf.image_opacity)
		self.connect('check_resize', self._update_image, pixbuf, image)
		return image

	def _update_image(self, w, pixbuf, image):
		alloc = self.box.get_allocation()
		if image.w_chk == alloc.width: return
		image.w_chk = alloc.width
		aspect = pixbuf.get_width() / pixbuf.get_height()
		w, h = alloc.width, int(alloc.width / aspect)
		pixbuf_resized = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
		image.set_from_pixbuf(pixbuf_resized)


class ScrollerApp(Gtk.Application):

	def __init__(self, src_paths_iter, conf):
		self.src_paths_iter, self.conf = src_paths_iter, conf
		super(ScrollerApp, self).__init__()
		if self.conf.app_id: self.set_application_id(self.conf.app_id)
		if self.conf.no_session: self.set_property('register-session', False)

	def do_activate(self):
		win = ScrollerWindow(self, self.src_paths_iter, self.conf)
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
	conf = ScrollerConf()

	import argparse
	parser = argparse.ArgumentParser(
		description='Display image-scroller window.')

	group = parser.add_argument_group('Image sources')
	group.add_argument('image_path', nargs='*',
		help='Path to file(s) or directories (will be searched recursively) to display images from.'
			' All found files will be treated as images,'
				' use e.g. find/grep/xargs for filename-based filtering.'
			' If no paths are provided, current'
				' directory is used by default. See also --file-list option.')
	group.add_argument('-f', '--file-list', metavar='path',
		help='File with a list of image files/dirs paths to use, separated by newlines.'
			' Can be a fifo or pipe, use "-" to read it from stdin.')

	group = parser.add_argument_group('Scrolling')
	group.add_argument('-q', '--queue',
		metavar='count[:preload-thresh]',
		help='Number of images scrolling through a window and at which position'
				' (0-1.0 with 0 being "top" and 1.0 "bottom") to pick/load/insert new images.'
			' Format is: count[:preload-theshold]. Examples: 4:0.8, 10:0.5, 5:0.9.'
			' Default: {}:{}'.format(conf.queue_size, conf.queue_preload_at))
	group.add_argument('-a', '--auto-scroll', metavar='px[:interval]',
		help='Auto-scroll by specified number of pixels with specified interval (1s by defaul).')

	group = parser.add_argument_group('Appearance')
	group.add_argument('-o', '--opacity',
		type=float, metavar='0-1.0', default=1.0,
		help='Opacity of the window contents - float value in 0-1.0'
				' range, with 0 being fully-transparent and 1.0 fully opaque.'
			' Should only have any effect with compositing Window Manager.'
			' Default: %(default)s.')
	group.add_argument('-p', '--pos', metavar='(WxH)(+X)(+Y)',
		help='Set window size and/or position hints for WM (usually followed).'
			' W/H values can be special "S" to use screen size, e.g. SxS is "fullscreen".'
			' X/Y offsets must be specified in that order, if at all, with positive'
				' values (prefixed with "+") meaning offset from top-left corner'
				' of the screen, and negative - bottom-right.'
			' If not specified (default), all are left for Window Manager to decide/remember.'
			' Examples: 800x600, -0+0 (move to top-right corner), 200xS+0.')
	group.add_argument('-s', '--spacing',
		type=int, metavar='px', default=conf.vbox_spacing,
		help='Padding between images, in pixels. Default: %(default)spx.')
	group.add_argument('-x', '--wm-hints', metavar='(+|-)hint(,...)',
		help=( 'Comma or space-separated list of WM hints to set/unset for the window.'
				' All of these can have boolean yes/no or unspecified/default values.'
				' Specifying hint name in the list will have it explicity set (i.e. "yes/true" value),'
					' and preceding name with "-" will have it explicitly unset instead ("no/false").'
				' List of recognized hints: [ {} ].'
				' Example: keep_top -decorated skip_taskbar skip_pager -accept_focus.' )\
			.format(', '.join(conf.wm_hints_all)))
	group.add_argument('-t', '--wm-type-hints', metavar='hint(,...)',
		help=( 'Comma or space-separated list of window type hints for WM.'
				' Similar to --wm-hints in general, but are'
					' combined separately to set window type hint value.'
				' List of recognized type-hints: [ {} ], all are unset by default.'
				' Probably does not make sense to use multiple of these at once.' )\
			.format(', '.join(conf.wm_type_hints_all)))
	group.add_argument('-i', '--icon-name', metavar='icon',
		help='Name of the XDG icon to use for the window.'
			' Can be icon from a theme, one of the default gtk ones, and such.'
			' See XDG standards for how this name gets resolved into actual file path.'
			' Example: image-x-generic.')

	group = parser.add_argument_group('Misc / debug')
	parser.add_argument('-n', '--no-register-session', action='store_true',
		help='Do not try register app with any session manager.'
			' Can be used to get rid of Gtk-WARNING messages'
				' about these and to avoid using dbus, but not sure how/if it actually works.')
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

	if opts.auto_scroll:
		try: px, s = map(float, opts.auto_scroll.split(':', 1))
		except ValueError: px, s = float(opts.auto_scroll), 1
		conf.auto_scroll = px, s
	if opts.pos:
		m = re.search(r'^((?:\d+|S)x(?:\d+|S))?([-+]\d+)?([-+]\d+)?$', opts.pos)
		if not m: parser.error('Invalid size/position spec: {!r}', opts.pos)
		size, x, y = m.groups()
		if size: conf.win_w, conf.win_h = size.split('x', 1)
		if x: conf.win_x = x
		if y: conf.win_y = y
	if opts.queue:
		try: qs, q_pos = opts.queue.split(':', 1)
		except ValueError: qs, q_pos = opts.queue, None
		if qs: conf.queue_size = int(qs)
		if q_pos: conf.queue_preload_at = float(q_pos)
	if opts.wm_hints:
		conf.wm_hints = dict(
			(hint.lstrip('+-'), not hint.startswith('-'))
			for hint in opts.wm_hints.replace(',', ' ').split() )
	if opts.wm_type_hints:
		for k in opts.wm_type_hints.replace(',', ' ').split():
			conf.wm_type_hints |= conf.wm_type_hints_all[k]
	if opts.icon_name: conf.win_icon = opts.icon_name
	conf.vbox_spacing = opts.spacing
	conf.image_opacity = opts.opacity
	conf.no_session = opts.no_register_session

	log.debug('Starting application...')
	ScrollerApp(src_paths_iter, conf).run()

if __name__ == '__main__':
	import signal
	signal.signal(signal.SIGINT, signal.SIG_DFL)
	sys.exit(main())
