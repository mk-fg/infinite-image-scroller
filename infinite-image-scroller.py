#!/usr/bin/env python3

import itertools as it, operator as op, functools as ft, datetime as dt
import pathlib as pl, collections as cs, dataclasses as dc
import os, sys, re, logging, enum, textwrap, random, signal

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GLib', '2.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib


class LogMessage:
	def __init__(self, fmt, a, k): self.fmt, self.a, self.k = fmt, a, k
	def __str__(self): return self.fmt.format(*self.a, **self.k) if self.a or self.k else self.fmt

class LogStyleAdapter(logging.LoggerAdapter):
	def __init__(self, logger, extra=None):
		super().__init__(logger, extra or {})
	def log(self, level, msg, *args, **kws):
		if not self.isEnabledFor(level): return
		log_kws = {} if 'exc_info' not in kws else dict(exc_info=kws.pop('exc_info'))
		msg, kws = self.process(msg, kws)
		self.logger.log(level, LogMessage(msg, args, kws), **log_kws)

get_logger = lambda name: LogStyleAdapter(logging.getLogger(name))

dd = lambda text: re.sub( r' \t+', ' ',
	textwrap.dedent(text).strip('\n') + '\n' ).replace('\t', '  ')


@dc.dataclass
class Pos:
	x: int = 0
	y: int = 0
	w: int = 0
	h: int = 0

@dc.dataclass
class Image:
	path: str
	gtk: Gtk.Image
	pb_src: GdkPixbuf.Pixbuf = None # source-size pixbuf, only used with sync loading
	pb_proc: GdkPixbuf.Pixbuf = None # only used with helper module
	sz: int = None # in dim_scale
	sz_scroll: int = None
	sz_chk: int = None
	displayed: bool = False
	scrolled: bool = False

class ScrollDirection(enum.IntEnum):
	left = 0; right = 1; up = 2; down = 3

ScrollAdjust = enum.Enum('ScrollAdjust', 'slower faster toggle')
BrightnessAdaptDir = enum.IntEnum('BrightnessAdapt', 'both up down')

class ISODT:
	def __init__(self): self.dt = dt.datetime.now()
	def __getattr__(self, k): return self.dt.isoformat(' ', k)
	def __getitem__(self, k): return self.dt.strftime(k)


class ScrollerConf:

	misc_app_id = 'net.fraggod.infinite-image-scroller'
	misc_no_session = False
	misc_box_spacing = 3
	misc_event_delay = 0.2 # debounce delay for scrolling, window resizing, clicks and such

	win_title = 'infinite-image-scroller'
	win_role = 'scroller-main'
	win_icon = ''
	win_pos = ''
	win_w = win_h = 0
	win_x = win_y = 0
	win_hints = win_type_hints = ''

	_win_size_default = 700, 500
	_win_css = dd('''
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
		#infinite-image-scroller, #infinite-image-scroller * { background: transparent; }''')
	_win_hints_all = (
		' focus_on_map modal resizable hide_titlebar_when_maximized'
		' stick maximize fullscreen keep_above keep_below decorated'
		' deletable skip_taskbar skip_pager urgency accept_focus'
		' auto_startup_notification mnemonics_visible focus_visible' ).split()
	_win_type_hints_all = dict(
		(e.value_nick, v) for v, e in Gdk.WindowTypeHint.__enum_values__.items() if v )

	scroll_direction = 'down'
	scroll_auto = '' # px:interval
	scroll_adjust_k = 2
	scroll_pause = 0.0
	scroll_queue_size = 10
	scroll_queue_preload_at = 0.6
	_scroll_auto_key_start = 1, 0.01

	image_proc_threads = 0
	image_opacity = 1.0
	image_brightness = 1.0
	image_brightness_adapt = '' # [+/-](0-1.0)
	_image_brightness_adapt_k = 0.0
	_image_brightness_adapt_dir = BrightnessAdaptDir.both
	image_scale_algo = 'bilinear'
	image_open_attempts = 3
	_image_proc_module = None

	# Key combos format is lowercase "[mod1 ...] key, ...", with modifier keys alpha-sorted
	# Use --debug option to see which exact key-sums get pressed
	keys_quit = 'q, control q, control w, escape'
	keys_scroll_faster = 'm'
	keys_scroll_slower = 'n'
	keys_scroll_toggle = 'p, space'
	keys_click_print_format = '[{isodt.seconds}] {image.path}' # vars: n, isodt, image
	_keys_click_n = 0

	_conf_sections = 'misc', 'win', 'wm', 'scroll', 'image', 'keys'
	_conf_file_name = 'infinite-image-scroller.ini'

	def __init__(self, **kws):
		for k, v in kws.items():
			if not hasattr(self, k): raise AttributeError(k)
			setattr(self, k, v)

	def update_from_files(self, *paths, home_lookups=True):
		if home_lookups:
			for p in filter(None, os.environ.get('XDG_CONFIG_DIRS', '').split(':')):
				p = pl.Path(p) / self._conf_file_name
				if p.exists(): self.update_from_file(p)
			p = os.environ.get('XDG_CONFIG_HOME')
			if p: p = pl.Path(p)
			elif p := os.environ.get('HOME'): p = pl.Path(p) / '.config'
			if p and (p := p / self._conf_file_name) and p.exists(): self.update_from_file(p)
		for p in paths: self.update_from_file(p)

	def update_from_file(self, path):
		import configparser
		log.debug('Updating configuration from file: {}', path)
		conf = configparser.ConfigParser(allow_no_value=True)
		conf.optionxform = lambda k: k
		with open(path) as src: conf.read_file(src)
		for sec in self._conf_sections:
			sec_pre = f'{sec}_'
			for k in dir(self):
				if not k.startswith(sec_pre): continue
				v = getattr(self, k)
				if isinstance(v, str): get_val = lambda *a: str(conf.get(*a))
				elif isinstance(v, bool): get_val = conf.getboolean
				elif isinstance(v, int): get_val = conf.getint
				elif isinstance(v, float): get_val = conf.getfloat
				else: continue
				for kc in k, k.replace('_', '-'):
					try: setattr(self, k, get_val(sec, kc[len(sec_pre):]))
					except configparser.Error: pass
					else: break

	def pprint(self, title=None):
		cat, chk = None, re.compile(
			'^({})_(.*)$'.format('|'.join(map(re.escape, self._conf_sections))) )
		if title: print(f';; {title}')
		for k in self.__class__.__dict__.keys():
			m = chk.search(k)
			if not m: continue
			v, cat_chk = getattr(self, k), m.group(1).replace('_', '-')
			if cat_chk != cat:
				cat = cat_chk
				print(f'\n[{cat}]')
			if isinstance(v, bool): v = ['no', 'yes'][v]
			elif isinstance(v, int): v = int(v)
			k, v = m.group(2).replace('_', '-'), str(v).replace('\t', '  ')
			print(f'{k} = {v}')


class ScrollerWindow(Gtk.ApplicationWindow):

	def __init__(self, app, src_paths_iter, conf):
		super().__init__(name='infinite-image-scroller', application=app)
		self.app, self.src_paths_iter, self.conf = app, src_paths_iter, conf
		self.log = get_logger('win')

		self.set_title(self.conf.win_title)
		self.set_role(self.conf.win_role)
		if self.conf.win_icon:
			self.log.debug('Using icon: {}', self.conf.win_icon)
			self.set_icon_name(self.conf.win_icon)

		self.pp = self.conf._image_proc_module
		if self.pp:
			self.pp, threading, queue = self.pp
			self.thread_queue = queue.Queue()
			self.thread_list = list(
				threading.Thread( name=f'set_pixbuf.{n}',
					target=self.image_set_pixbuf_thread, daemon=True )
				for n in range(self.conf.image_proc_threads) )
			for t in self.thread_list: t.start()
			self.thread_kill = threading.get_ident(), signal.SIGUSR1
			GLib.unix_signal_add( GLib.PRIORITY_DEFAULT,
				self.thread_kill[1], self.image_set_pixbuf_thread_cb )
			self.thread_results = list()

		self.init_widgets()


	def init_widgets(self):
		css = Gtk.CssProvider()
		css.load_from_data(self.conf._win_css.encode())
		Gtk.StyleContext.add_provider_for_screen(
			Gdk.Screen.get_default(), css,
			Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION )

		self.dim_scroll_v = self.dim_scale_w = bool(self.conf.scroll_direction.value & 2) # up/down
		self.dim_scroll_rev = not self.conf.scroll_direction.value & 1 # left/up

		self.scroll = Gtk.ScrolledWindow()
		self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.ALWAYS)
		self.add(self.scroll)
		self.box = Gtk.VBox if self.dim_scroll_v else Gtk.HBox
		self.box = self.box(spacing=self.conf.misc_box_spacing, expand=True)
		self.scroll.add(self.box)
		self.box_images, self.box_images_init = cs.deque(), True
		self.ev_timers = dict()

		self.dim_scale, self.dim_scroll, self.dim_scroll_n = (
			('width', 'height', 1) if self.dim_scroll_v else ('height', 'width', 0) )
		self.dim_box_alloc = getattr(self.box, f'get_allocated_{self.dim_scroll}')
		self.dim_box_pack = self.box.pack_start if not self.dim_scroll_rev else self.box.pack_end
		self.dim_scroll_translate = ( (lambda a,b: a)
			if not self.dim_scroll_rev else (lambda a,b: max(0, b - a)) )
		self.dim_scroll_for_image = lambda img: getattr(img.get_allocation(), self.dim_scroll)
		self.dim_scroll_for_pixbuf = lambda pb: getattr(pb, f'get_{self.dim_scroll}')()

		self.scroll_adj = ( self.scroll.get_vadjustment()
			if self.dim_scroll_v else self.scroll.get_hadjustment() )
		self.scroll_adj.connect( 'value-changed',
			ft.partial(self.ev_debounce, ev='scroll', cb=self.scroll_update) )
		self.scroll_adj_image = None

		hints = dict.fromkeys(self.conf._win_hints_all)
		hints.update(self.conf.win_hints or dict())
		for k in list(hints):
			setter = getattr(self, f'set_{k}', None)
			if not setter: setter = getattr(self, f'set_{k}_hint', None)
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
		self.set_type_hint(self.conf.win_type_hints)

		self.connect('composited-changed', self.set_visual_rgba)
		self.connect('screen-changed', self.set_visual_rgba)
		self.set_visual_rgba(self)

		self.set_default_size(*self.conf._win_size_default)
		self.place_window_ev = None
		self.place_window(self)
		self.place_window_ev = self.connect('configure-event', self.place_window)
		self.connect('key-press-event', self.window_key)

		self.connect( 'configure-event',
			ft.partial(self.ev_debounce, ev='set-pixbufs', cb=self.image_set_pixbufs) )
		if self.conf.keys_click_print_format:
			self.connect( 'button-press-event', lambda w, ev:
				self.ev_debounce(ev.x, ev.y, ev='click', cb=self.image_click, now=True) )

		self.scroll_timer = self.scroll_linger_last = None
		if self.conf.scroll_auto: self.scroll_adjust(ScrollAdjust.toggle)


	def ev_debounce_is_set(self, ev): return ev in self.ev_timers
	def ev_debounce_clear(self, ev):
		timer = self.ev_timers.pop(ev, None)
		if timer is not None: GLib.source_remove(timer)
	def ev_debounce_cb(self, ev, cb, ev_args):
		self.ev_timers.pop(ev, None)
		if cb: cb(*ev_args)
	def ev_debounce(self, *ev_args, ev=None, cb=None, delay=None, now=False):
		'Delay and/or prevent repeated events.'
		if not now: self.ev_debounce_clear(ev)
		elif ev in self.ev_timers: return
		else: cb(*ev_args); cb = None
		if delay is None: delay = self.conf.misc_event_delay
		self.ev_timers[ev] = GLib.timeout_add(
			delay * 1000, self.ev_debounce_cb, ev, cb, ev_args )
	def ev_delay(self, ev, delay, cb, *ev_args, **debounce_kws):
		self.ev_debounce(*ev_args, ev=ev, cb=cb, delay=delay, **debounce_kws)


	def set_visual_rgba(self, w, *ev_data):
		visual = w.get_screen().get_rgba_visual()
		if visual: w.set_visual(visual)

	def place_window(self, w, *ev_data):
		if self.place_window_ev:
			self.disconnect(self.place_window_ev)
			self.place_window_ev = None
		dsp, sg = w.get_screen().get_display(), Pos()
		geom = dict(S=sg)
		for n in range(dsp.get_n_monitors()):
			rct = dsp.get_monitor(n).get_geometry()
			mg = geom[f'M{n+1}'] = Pos(x=rct.x, y=rct.y, w=rct.width, h=rct.height)
			sg.w, sg.h = max(sg.w, mg.x + mg.w), max(sg.h, mg.y + mg.h)
		ww = wh = None
		if self.conf.win_w and self.conf.win_h:
			get_val = lambda v,k: int(v) if v.isdigit() else getattr(geom[v], k)
			ww, wh = get_val(self.conf.win_w, 'w'), get_val(self.conf.win_h, 'h')
			w.resize(ww, wh)
			self.log.debug('win-resize: {} {}', ww, wh)
		if self.conf.win_x or self.conf.win_y:
			if not (ww or wh): ww, wh = w.get_size()
			wx, wy = w.get_position()
			get_pos = lambda v,k,wv: (
				(int(v[1:]) if v[0] != '-' else (sg[k] - wv - int(v[1:])))
				if v[0] in '+-' else getattr(geom[v], k) )
			if self.conf.win_x: wx = get_pos(self.conf.win_x, 'x', ww)
			if self.conf.win_y: wy = get_pos(self.conf.win_y, 'y', wh)
			self.log.debug('win-move: {} {}', wx, wy)
			w.move(wx, wy)

	_key_sums = _key_masks = None
	def window_key(self, w, ev):
		if not self._key_masks:
			self._key_masks = dict()
			for st, mod in Gdk.ModifierType.__flags_values__.items():
				if ( len(mod.value_names) != 1
					or not mod.first_value_nick.endswith('-mask') ): continue
				assert st not in self._key_masks, [mod.first_value_nick, self._key_masks[st]]
				mod = mod.first_value_nick[:-5]
				if mod.startswith('modifier-reserved-'): mod = 'res-{}'.format(mod[18:])
				self._key_masks[st] = mod
		if not self._key_sums:
			self._key_sums = dict()
			for k, action in [
					('quit', 'q'), *((f'scroll_{k.name}', k) for k in ScrollAdjust) ]:
				self._key_sums[action] = list(filter( None,
					map(str.strip, getattr(self.conf, f'keys_{k}').split(',')) ))
		chk, keyval = ev.get_keyval()
		if not chk: return
		key_sum, key_name = list(), Gdk.keyval_name(keyval)
		for st, mod in self._key_masks.items():
			if ev.state & st == st: key_sum.append(mod)
		key_sum = ' '.join(sorted(key_sum) + [key_name]).lower()
		self.log.debug('key-press-event: {!r}', key_sum)

		for action, key_sums in self._key_sums.items():
			if key_sum not in key_sums: continue
			if action == 'q': self.app.quit()
			elif isinstance(action, ScrollAdjust): self.scroll_adjust(action)


	def scroll_update(self, adj, offset=None, repeat=False):
		'Hook to load new images on v/h gtk adjustement (scroll) value changes.'
		self.ev_debounce_clear('scroll')
		pos_max = self.dim_box_alloc() - self.get_size()[self.dim_scroll_n]
		pos = self.dim_scroll_translate(adj.get_value(), pos_max)

		if offset:
			if ( self.conf.scroll_pause and self.scroll_timer
					and (oc := self.image_at_center(offset)) is not None ):
				offset = oc
				self.scroll_adjust(ScrollAdjust.toggle)
				self.ev_delay( 'scroll-pause',
					self.conf.scroll_pause, self.scroll_adjust, ScrollAdjust.toggle )
			pos += offset
			adj.set_value(self.dim_scroll_translate(pos, pos_max))

		if ( pos >= pos_max * self.conf.scroll_queue_preload_at
				and self.box_images and (
				sum(bool(img.displayed) for img in self.box_images) / len(self.box_images)
					> self.conf.scroll_queue_preload_at )):
			pos += self.image_cycle()
			adj.set_value(self.dim_scroll_translate(pos, pos_max))
		# Check is to avoid expensive updates/reloads while window is resized
		if not self.ev_debounce_is_set('set-pixbufs'): self.image_set_pixbufs()
		return repeat

	def image_at_center(self, offset_max):
		'Gets offset-from-win-center of next image about to be there or None.'
		images = list(img for img in self.box_images if img.displayed and img.gtk)
		if not images: return
		sz_win = getattr(self.scroll.get_allocation(), self.dim_scroll)
		for image in images:
			pos = image.gtk.translate_coordinates(self.scroll, 0, 0)
			if not pos or (pos := pos[self.dim_scroll_n]) == -1: continue # not realized yet
			if self.dim_scroll_rev: pos = (sz_win - image.sz_scroll) - pos
			offset = pos - (sz_win/2 - image.sz_scroll/2)
			if offset < 0:
				if not self.scroll_linger_last: # linger on first image
					self.scroll_linger_last = image
					return 0
				continue # moved past center - ignore
			if offset < offset_max and self.scroll_linger_last is not image:
				self.scroll_linger_last = image
				return offset
			return # only need to check first image with offset>0

	def image_cycle(self):
		'Adds/removes images and returns scroll position adjustment based on their size.'
		offset = offset_rev = 0
		image = ...
		while image is ... or len(self.box_images) < self.conf.scroll_queue_size:
			image = self.image_add()
			if not image: break
			if image.displayed: # delayed loading runs image_set_scroll on gtk event
				offset_rev += self.dim_scroll_for_image(image.gtk)
				offset_rev += self.conf.misc_box_spacing
		while len(self.box_images) > self.conf.scroll_queue_size:
			image = self.box_images.popleft()
			offset += self.dim_scroll_for_image(image.gtk)
			self.image_remove(image)
			offset += self.conf.misc_box_spacing
		offset = -(offset if not self.dim_scroll_rev else offset_rev)
		return offset

	def image_add(self):
		'Adds image and returns it, or returns None if there is nothing more to add.'
		for n in range(self.conf.image_open_attempts):
			try: p = next(self.src_paths_iter)
			except StopIteration: p = None
			if not p: return
			image = self.image_load(p)
			if image: break
		else:
			self.log.error( 'Failed to get new image'
				' in {} attempt(s), giving up', self.conf.image_open_attempts )
			return
		self.dim_box_pack(image.gtk, False, False, 0)
		self.box_images.append(image)
		image.gtk.show()
		return image

	def image_remove(self, image):
		self.box.remove(image.gtk)
		image.gtk.destroy()

	def image_load(self, path):
		self.log.debug('Adding image: {}', path)
		image = Image(path=path, gtk=Gtk.Image())
		if not self.pp:
			try: image.pb_src = GdkPixbuf.Pixbuf.new_from_file(path)
			except Exception as err:
				self.log.error( 'Failed to create gdk-pixbuf'
					' from file: [{}] {}', err.__class__.__name__, err )
				return
		if self.conf.image_opacity < 1.0:
			image.gtk.set_opacity(self.conf.image_opacity)
		return image

	def image_click(self, *xy):
		'Handler for window clicks to translate event x/y to image names.'
		self.conf._keys_click_n += 1
		p, fmt = xy[self.dim_scroll_n], self.conf.keys_click_print_format
		images = list(img for img in self.box_images if img.displayed and img.gtk)
		for image in images:
			if not (image.displayed and image.gtk): return
			if not (xy := image.gtk.translate_coordinates(self, 0, 0)): continue
			if (o := xy[self.dim_scroll_n]) <= p <= o + image.sz_scroll:
				print(fmt.format( isodt=ISODT(),
					image=image, n=self.conf._keys_click_n ), flush=True)
				break
		else:
			self.log.error( 'Failed to match window click'
				' event with any of the image positions (n={:,d})', len(images) )


	def image_set_pixbufs(self, *ev_args, init=False):
		'Must be called to set image widget contents to resized pixbufs'
		if self.box_images_init:
			self.box_images_init, init = False, True
			init_sz = getattr(self.get_allocation(), self.dim_scroll) * 1.5
			for n in range(self.conf.scroll_queue_size): self.image_add()

		self.ev_debounce_clear('set-pixbufs')
		sz = getattr(self.get_allocation(), self.dim_scale)
		for image in list(self.box_images):
			if image.sz_chk == sz: continue
			image.sz_chk = sz

			if image.pb_src: # simple sync processing with no helper module
				w, h = image.pb_src.get_width(), image.pb_src.get_height()
				w, h = ((sz, int(sz / (w / h))) if self.dim_scale_w else (int(sz * (w / h)), sz))
				pixbuf = image.pb_src.scale_simple(w, h, self.conf.image_scale_algo)
				image.gtk.set_from_pixbuf(pixbuf)
				image.sz, image.sz_scroll, image.displayed = w, h, True

			else: # background pixbuf_proc.so threads, except when init=True
				image.sz, image.pb_proc = sz, None
				log.debug('pixbuf_proc [{}]: {}', 'init' if init else 'queue', image.path)
				if init and init_sz > 0:
					self.image_set_pixbuf_proc(image)
					if image.pb_proc: init_sz -= self.dim_scroll_for_pixbuf(image.pb_proc)
					self.thread_results.append(image)
				else: self.thread_queue.put_nowait(image)

		if init and self.pp: self.image_set_pixbuf_thread_cb()


	def image_set_pixbuf_proc(self, image):
		sz = image.sz
		w, h = ((sz, -1) if self.dim_scale_w else (-1, sz))
		try:
			buff, w, h, rs, alpha = self.pp.process_image_file(
				image.path, w, h, int(self.conf.image_scale_algo), self.conf.image_brightness,
				int(self.conf._image_brightness_adapt_dir), self.conf._image_brightness_adapt_k )
		except self.pp.error as err:
			self.log.error('Failed to load/process image: {}', err)
			image.pb_proc = False
			return
		if image.sz != sz: return # was re-queued
		image.pb_proc = GdkPixbuf.Pixbuf\
			.new_from_data(buff, GdkPixbuf.Colorspace.RGB, alpha, 8, w, h, rs)

	def image_set_pixbuf_thread(self):
		while True:
			image = self.thread_queue.get()
			log.debug('pixbuf_proc [thread]: {}', image.path)
			self.image_set_pixbuf_proc(image)
			self.thread_results.append(image)
			signal.pthread_kill(*self.thread_kill)

	def image_set_pixbuf_thread_cb(self):
		# Note: these are only called in series by glib, and do not interrupt each other
		while True:
			try: image = self.thread_results.pop()
			except IndexError: break
			log.debug('pixbuf_proc [signal]: {}', image.path)
			if image.pb_proc is False:
				self.box_images.remove(image)
				self.image_remove(image)
			else:
				image.gtk.set_from_pixbuf(image.pb_proc)
				image.sz_scroll = getattr(image.pb_proc, f'get_{self.dim_scroll}')()
				if self.dim_scroll_rev: # scroll pos will change when image is drawn
					image.gtk.connect('size-allocate', ft.partial(self.image_set_scroll, image))
				image.pb_proc, image.displayed = None, True
		return True

	def image_set_scroll(self, image, w, ev):
		if image.scrolled: return
		image.scrolled = True
		# This seem to cause some scroll-jumps, not sure why, maybe wrong gtk event?
		offset = self.scroll_adj.get_value()
		offset += self.dim_scroll_for_image(image.gtk)
		offset += self.conf.misc_box_spacing
		self.scroll_adj.set_value(offset)


	def scroll_adjust(self, adj):
		'Auto-scrolling start/pause and speed control function.'
		self.ev_debounce_clear('scroll-pause')
		px, s = self.conf.scroll_auto or (0, 0)
		adj_k = self.conf.scroll_adjust_k

		if adj is ScrollAdjust.toggle:
			if self.scroll_timer: px = s = 0 # pause
			elif not (px and s): px, s = self.conf._scroll_auto_key_start
			else: s += 1e-6 # just to trigger change check below

		elif adj is ScrollAdjust.faster:
			if not self.conf.scroll_auto: # just start with any parameters
				return self.scroll_adjust(ScrollAdjust.toggle)
			if s < 1/120: px *= adj_k # bump px jumps if it's >120fps already
			else: s /= adj_k

		elif adj is ScrollAdjust.slower:
			if px <= 1: px, s = 1, s * adj_k # bump interval instead of sub-px skips
			else: px /= adj_k

		if (px, s) == self.conf.scroll_auto:
			return log.warning(
				'Scroll-adjust BUG [{}]: [run={} speed={}] -> no changes!',
				adj.name, bool(self.scroll_timer), self.conf.scroll_auto )

		log.debug( 'Scroll-adjust [{}]: [run={} speed={}] -> [run={} speed={}]',
			adj.name, bool(self.scroll_timer), self.conf.scroll_auto, bool(px and s), (px, s) )
		if self.scroll_timer: GLib.source_remove(self.scroll_timer)
		if not (px and s): self.scroll_timer = None
		else:
			self.conf.scroll_auto = px, s
			self.scroll_timer = GLib.timeout_add(s * 1000, ft.partial(
				self.scroll_update, self.scroll_adj, offset=px, repeat=True ))


class ScrollerApp(Gtk.Application):

	def __init__(self, src_paths_iter, conf):
		self.src_paths_iter, self.conf = src_paths_iter, conf
		super().__init__()
		if self.conf.misc_app_id:
			self.set_application_id(self.conf.misc_app_id.format(pid=os.getpid()))
		if self.conf.misc_no_session: self.set_property('register-session', False)

	def do_activate(self):
		win = ScrollerWindow(self, self.src_paths_iter, self.conf)
		win.connect('delete-event', lambda w,*data: self.quit())
		win.show_all()


def shuffle_iter(src_paths, crop_ratio=0.25):
	src_paths, used = list(src_paths), 0
	while len(src_paths) > used:
		n = random.randint(0, len(src_paths)-1)
		p = src_paths[n]
		if not p: continue
		src_paths[n], used = None, used + 1
		if used >= len(src_paths) * crop_ratio:
			used, src_paths = 0, list(filter(None, src_paths))
		yield p

def loop_iter(src_paths_func):
	while True:
		for p in src_paths_func(): yield p

def file_iter(src_paths):
	for path in map(pl.Path, src_paths):
		if not path.exists():
			log.warn('Path does not exists: {}', path)
			continue
		if path.is_dir():
			for root, dirs, files in os.walk(str(path)):
				root = pl.Path(root)
				for fn in files: yield str(root / fn)
		else: yield str(path)


def main(args=None, conf=None):
	if not conf: conf = ScrollerConf()
	scale_algos = 'bilinear hyper nearest tiles'.split()

	import argparse
	parser = argparse.ArgumentParser(
		formatter_class=argparse.RawTextHelpFormatter,
		description='Display image-scroller window.')

	group = parser.add_argument_group('Image sources')
	group.add_argument('image_path', nargs='*', help=dd('''
		Path to file(s) or directories
			(will be searched recursively) to display images from.
		All found files will be treated as images,
			use e.g. find/grep/xargs for filename-based filtering.
		If no paths are provided, current
			directory is used by default. See also --file-list option.'''))
	group.add_argument('-f', '--file-list', metavar='path', help=dd('''
		File with a list of image files/dirs paths to use, separated by newlines.
		Can be a fifo or pipe, use "-" to read it from stdin.'''))
	group.add_argument('-r', '--shuffle', action='store_true', help=dd('''
		Read full list of input images
			(dont use infinite --file-list) and shuffle it.'''))
	group.add_argument('-l', '--loop', action='store_true', help=dd('''
		Loop (pre-buffered) input list of images infinitely.
		Will re-read any dirs in image_path on each loop cycle,
			and reshuffle files if -r/--shuffle is also specified.'''))

	group = parser.add_argument_group('Image processing')
	group.add_argument('-z', '--scaling-interp',
		default=scale_algos[0], metavar='algo', help=dd(f'''
			Interpolation algorithm to use to scale images to window size.
			Supported ones: {", ".join(scale_algos)}. Default: %(default)s.
			Can be specified by full name, prefix\
				(e.g. "h" for "hyper") or digit (1={scale_algos[0]}).'''))
	group.add_argument('-b', '--brightness', type=float, metavar='float', help=dd('''
		Adjust brightness of images before displaying them via HSP algorithm,
			multiplying P by specified coefficient value (>1 - brighter, <1 - darker).
		For more info on HSP, see http://alienryderflex.com/hsp.html
		Requires compiled pixbuf_proc.so module importable somewhere, e.g. same dir as script.'''))
	group.add_argument('-B', '--brightness-adapt', metavar='(+/-)(0-1.0)', help=dd('''
		Dynamically adjust brightness of each image if average (median)
			HSP pixel brightness value is below specified argument within 0-1 range.
		Adjustment is done before -b/--brightness,
			and uses "target / average" coefficient for each pixel.
		Value can be prefixed by + or - to only adjust brightness in one direction (+/up, -/down).
		Requires compiled pixbuf_proc.so module importable somewhere, e.g. same dir as script.'''))
	group.add_argument('-m', '--proc-threads', type=int, metavar='n', help=dd('''
		Number of background threads to use for loading and processing images.
		Requires pixbuf_proc.so module to be loaded if value is specified,
			and otherwise defaults to 0, which will translate to CPU thread count.'''))

	group = parser.add_argument_group('Scrolling')
	group.add_argument('-d', '--scroll-direction', metavar='direction', help=dd(f'''
		Direction for scrolling - left, right, up, down (can be specified by prefix, e.g. "r").
		This determines where scrollbar will be, how images will be scaled
			(either to window width or height), -a/--auto-scroll direction, as well as
			on which window side new images will be appended (when scrolling close to it).'''))
	group.add_argument('-q', '--queue', metavar='count[:preload-thresh]', help=dd(f'''
		Number of images scrolling through a window and at which position
			(0-1.0 with 0 being "top" and 1.0 "bottom") to pick/load/insert new images.
		Format is: count[:preload-theshold].
		Examples: 4:0.8, 10:0.5, 5:0.9. Default: \
			{conf.scroll_queue_size}:{conf.scroll_queue_preload_at}'''))
	group.add_argument('-a', '--auto-scroll', metavar='px[:interval]',
		help='Auto-scroll by specified number of pixels with specified interval (1s by default).')
	group.add_argument('-P', '--pause-on-image', type=float, metavar='seconds', help=dd('''
		Pause for specified number of seconds when each image is centered in the window.
		Only makes sense with -a/--auto-scroll option enabled.
		Depending on image/window dimensions, it might fit or be cut-off at the top and bottom.
		Use exact same image/window aspect ratio to have this create a kind of rolling slideshow.'''))

	group = parser.add_argument_group('Appearance')
	group.add_argument('-o', '--opacity', type=float, metavar='0-1.0', help=dd(f'''
		Opacity of the window contents - float value in 0-1.0 range,
			with 0 being fully-transparent and 1.0 fully opaque.
		Should only have any effect with compositing Window Manager.'''))
	group.add_argument('-p', '--pos', metavar='(WxH)(+X)(+Y)', help=dd('''
		Set window size and/or position hints for WM (usually followed).
		W/H values can be special "S" to use screen size,
			e.g. "SxS" (or just "S") is "fullscreen".
		X/Y offsets must be specified in that order, if at all, with positive
			values (prefixed with "+") meaning offset from top-left corner
			of the screen, and negative - bottom-right.
		Special values like "M1" (or M2, M3, etc) can
			be used to specify e.g. monitor-1 width/heigth/offsets,
			and if size is just "M1" or "M2", then x/y offsets default to that monitor too.
		If not specified (default), all are left for Window Manager to decide/remember.
		Examples: 800x600, -0+0 (move to top-right corner),
			S (full screen), 200xS+0, M2 (full monitor 2), M2+M1, M2x500+M1+524.
		"slop" tool - https://github.com/naelstrof/slop - can be used
			used to get this value interactively via mouse selection (e.g. "-p $(slop)").'''))
	group.add_argument('-s', '--spacing', type=int, metavar='px',
		help=f'Padding between images, in pixels. Default: {conf.misc_box_spacing}px.')
	group.add_argument('-x', '--wm-hints', metavar='(+|-)hint(,...)', help=dd('''
		Comma or space-separated list of WM hints to set/unset for the window.
		All of these can have boolean yes/no or unspecified/default values.
		Specifying hint name in the list will have it explicity set (i.e. "yes/true" value),
			and preceding name with "-" will have it explicitly unset instead ("no/false").
		List of recognized hints:
			{}.
		Example: keep_top -decorated skip_taskbar skip_pager -accept_focus.'''\
		.format('\n\t\t\t\t'.join(textwrap.wrap(', '.join(conf._win_hints_all), 75)))))
	group.add_argument('-t', '--wm-type-hints', metavar='hint(,...)', help=dd('''
		Comma or space-separated list of window type hints for WM.
		Similar to --wm-hints in general, but are
			combined separately to set window type hint value.
		List of recognized type-hints (all unset by default):
			{}.
		Probably does not make sense to use multiple of these at once.'''\
		.format('\n\t\t\t\t'.join(textwrap.wrap(', '.join(conf._win_type_hints_all), 75)))))
	group.add_argument('-i', '--icon-name', metavar='icon', help=dd('''
		Name of the XDG icon to use for the window.
		Can be icon from a theme, one of the default gtk ones, and such.
		See XDG standards for how this name gets resolved into actual file path.
		Example: image-x-generic.'''))

	group = parser.add_argument_group('Configuration file options')
	group.add_argument('-c', '--conf', metavar='file', action='append', help=dd(f'''
		Path of configuration file(s) to use.
		Can be specified mutliple times to use multiple config files,
			with values from the last one overriding earlier ones.
		{conf._conf_file_name} is looked up in XDG_CONFIG_* paths by default.
		Special value "-" can be used to disable loading config from any of the default locations.'''))
	group.add_argument('--conf-dump', action='store_true', help=dd('''
		Print all configuration settings, which will be used with
			currently detected (and/or specified) configuration file(s), and exit.'''))
	group.add_argument('--conf-dump-defaults', action='store_true', help=dd('''
		Print all default settings, which would be used'
			if no configuration file(s) were overriding these, and exit.'''))

	group = parser.add_argument_group('Misc / debug')
	group.add_argument('-n', '--no-register-session', action='store_true', help=dd('''
		Do not try register app with any session manager.
		Can be used to get rid of Gtk-WARNING messages
			about these and to avoid using dbus, but not sure how/if it actually works.'''))
	group.add_argument('-u', '--unique', action='store_true', help=dd('''
		Force application uniqueness via GTK application_id.
			I.e. exit immediately if another app instance is already running.'''))
	group.add_argument('--dump-css', action='store_true',
		help='Print css that is used for windows by default and exit.')
	group.add_argument('--quiet', action='store_true', help='Disable warning/error logging.')
	group.add_argument('--debug', action='store_true', help='Verbose operation mode.')

	opts = parser.parse_args(sys.argv[1:] if args is None else args)

	global log
	import logging
	if opts.debug: log = logging.DEBUG
	elif opts.quiet: log = logging.CRITICAL
	else: log = logging.WARNING
	logging.basicConfig(
		format='%(asctime)s :: %(levelname)s :: %(message)s',
		datefmt='%Y-%m-%d %H:%M:%S', level=log )
	log = get_logger('main')

	if opts.conf_dump_defaults: return conf.pprint('Default configuration options')
	conf_user_paths = opts.conf or list()
	try: conf_home_lookups = conf_user_paths.remove('-')
	except ValueError: conf_home_lookups = True
	conf_user_paths = list(pl.Path(p).expanduser() for p in conf_user_paths)
	for p in conf_user_paths:
		if not os.access(p, os.R_OK):
			parser.error(f'Specified config file is missing or inaccessible: {p}')
	conf.update_from_files(*conf_user_paths, home_lookups=conf_home_lookups)
	if opts.conf_dump: return conf.pprint('Current configuration file(s) options')
	if opts.dump_css: return print(conf._win_css.replace('\t', '  '), end='')

	src_paths = opts.image_path or list()
	if opts.file_list:
		if src_paths: parser.error('Either --file-list or image_path args can be specified, not both.')
		src_file = pl.Path(opts.file_list).open() if opts.file_list != '-' else sys.stdin
		src_paths = iter(lambda: src_file.readline().rstrip('\r\n').strip('\0'), '')
	elif not src_paths: src_paths.append('.')

	if opts.shuffle: random.seed()
	if opts.loop:
		src_func = lambda s=list(src_paths): file_iter(s)
		if opts.shuffle: src_func = lambda f=src_func: shuffle_iter(f())
		src_paths_iter = loop_iter(src_func)
	elif opts.shuffle: src_paths_iter = shuffle_iter(file_iter(src_paths))
	else: src_paths_iter = file_iter(src_paths)

	if opts.scaling_interp:
		algo = opts.scaling_interp.strip().lower()
		if algo not in scale_algos:
			if algo.isdigit():
				try: algo = scale_algos[int(algo) - 1]
				except: algo = None
			else:
				for a in scale_algos:
					if not a.startswith(algo): continue
					algo = a
					break
				else: algo = None
			if not algo: parser.error(f'Unknown scaling interpolation value: {opts.scaling_interp}')
			opts.scaling_interp = algo

	if opts.auto_scroll or conf.scroll_auto:
		if opts.auto_scroll: conf.scroll_auto = opts.auto_scroll
		try: px, s = map(float, conf.scroll_auto.split(':', 1))
		except ValueError: px, s = float(conf.scroll_auto), 1
		conf.scroll_auto = px, s
	if opts.pause_on_image is not None: conf.scroll_pause = opts.pause_on_image

	if opts.scroll_direction or conf.scroll_direction:
		if opts.scroll_direction: conf.scroll_direction = opts.scroll_direction
		v_chk = conf.scroll_direction.strip().lower()
		for v in ScrollDirection:
			if not v.name.startswith(v_chk): continue
			conf.scroll_direction = v
			break
		else: parser.error(f'Unrecognized -d/--scroll-direction value: {conf.scroll_direction}')

	if opts.pos or conf.win_pos:
		if opts.pos: conf.win_pos = opts.pos
		m = re.search(
			r'^((?:M?\d+|S)(?:x(?:M?\d+|S))?)?'
			r'([-+]M?\d+)?([-+]M?\d+)?$', conf.win_pos )
		if not m: parser.error(f'Invalid size/position spec: {conf.win_pos!r}')
		size, x, y = m.groups()
		size_fs = size if 'x' not in size else None
		if size:
			if size_fs: size = f'{size}x{size}'
			conf.win_w, conf.win_h = size.split('x', 1)
		if x: conf.win_x = x
		if y: conf.win_y = y
		if size_fs and not (x or y): conf.win_x = conf.win_y = size_fs

	if opts.queue:
		try: qs, q_pos = opts.queue.split(':', 1)
		except ValueError: qs, q_pos = opts.queue, None
		if qs: conf.scroll_queue_size = int(qs)
		if q_pos: conf.scroll_queue_preload_at = float(q_pos)

	if opts.wm_hints or conf.win_hints:
		if opts.wm_hints: conf.win_hints = opts.wm_hints
		conf.win_hints = dict(
			(hint.lstrip('+-'), not hint.startswith('-'))
			for hint in conf.win_hints.replace(',', ' ').split() )

	if opts.wm_type_hints or conf.win_type_hints or True:
		hints = opts.wm_type_hints or conf.win_type_hints
		conf.win_type_hints = Gdk.WindowTypeHint.NORMAL
		for k in hints.replace(',', ' ').split():
			conf.win_type_hints |= conf._win_type_hints_all[k]

	conf.image_scale_algo = getattr(
		GdkPixbuf.InterpType, (opts.scaling_interp or conf.image_scale_algo).upper() )
	if opts.icon_name: conf.win_icon = opts.icon_name
	if opts.spacing is not None: conf.misc_box_spacing = opts.spacing
	if opts.opacity is not None: conf.image_opacity = opts.opacity
	if opts.brightness is not None:
		conf.image_brightness = opts.brightness
		if conf.image_brightness < 0: parser.error('-b/--brightness value must be >0')
	if opts.proc_threads is not None: conf.image_proc_threads = opts.proc_threads
	if opts.no_register_session is not None: conf.misc_no_session = opts.no_register_session
	if not opts.unique: conf.misc_app_id += '.pid-{pid}'

	if opts.brightness_adapt: conf.image_brightness_adapt = opts.brightness_adapt
	if ba := conf.image_brightness_adapt:
		conf._image_brightness_adapt_k = abs(float(ba))
		conf._image_brightness_adapt_dir = \
			BrightnessAdaptDir[{'-': 'down', '+': 'up'}.get(ba[0], 'both')]
		if conf._image_brightness_adapt_k > 1:
			parser.error('-B/--brightness-adapt value without prefix must be in 0-1.0 range')
	else: conf._image_brightness_adapt_k = conf._image_brightness_adapt_dir = 0

	try:
		import pixbuf_proc, threading, queue
		conf._image_proc_module = pixbuf_proc, threading, queue
	except ImportError:
		if ( conf.image_brightness != 1.0 or
				conf._image_brightness_adapt_k or conf.image_proc_threads ):
			parser.error( 'pixbuf_proc.so module cannot be loaded, but is required'
				' with specified options - build it from pixbuf_proc.c in same repo as this script' )
	else:
		if not conf.image_proc_threads: conf.image_proc_threads = os.cpu_count()

	log.debug('Starting application...')
	ScrollerApp(src_paths_iter, conf).run()

if __name__ == '__main__':
	signal.signal(signal.SIGINT, signal.SIG_DFL)
	sys.exit(main())
