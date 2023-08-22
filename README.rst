=======================
Infinite Image Scroller
=======================
-----------------------------------------------------------
 Python GTK3 desktop app to scroll images across the window
-----------------------------------------------------------

Script loops through all specified image files/dirs, resizes each to window
width/height (preserving aspect ratio) and scrolls them one after another,
i.e. concatenated into one endless "image feed", but loading images only as
they're close to be scrolled into view.

Similar widget/behavior is usually called "image carousel" in web development.

``--auto-scroll`` option allows slideshow-like behavior, but otherwise one can
scroll through these manually.

Needs Python-3.x, GTK3_ and PyGObject_ to run.
These tend to come pre-installed on desktop linuxes.

There's also optional pixbuf_proc.c module which would need gcc and gtk headers
to build, and allows to load/scale images efficiently and asynchronously in
background threads without stuttering, as well as image brightness adjustment.

Aimed to be rather simple and straightforward, not a full-fledged image viewer.

See below for info on general usage and specific features.

.. _GTK3: https://www.gtk.org/
.. _PyGObject: https://pygobject.readthedocs.io/

.. contents::
  :backlinks: none

URLs for this project repository:

- https://github.com/mk-fg/infinite-image-scroller
- https://codeberg.org/mk-fg/infinite-image-scroller
- https://fraggod.net/code/git/infinite-image-scroller


Usage
-----

Some simple usage examples::

  % ./infinite-image-scroller.py image1.jpg image2.jpg image3.jpg
  % ./infinite-image-scroller.py --loop --shuffle path/to/my-image-dir
  % ./infinite-image-scroller.py -s0 -dr -a 5:0.01 --pause-on-image 5 /mnt/my-images/

Can also read a list or an endless feed of paths (files/dirs) from a
newline-separated list-file or stdin::

  % find -name '*.jpg' | shuf | ./infinite-image-scroller.py -f -
  % ./infinite-image-scroller.py -f carousel.list --auto-scroll 10:0.1

``-a/--auto-scroll`` option takes ``px[:seconds]`` parameter for scrolling
"step" and how often it is repeated (default is 1 second, if omitted), i.e.
``-a 10:0.1`` means "scroll by 10px every 0.1 seconds".

More fancy display options - scrolling transparent 800px
sticky/undecorated/unfocusable/bottom-layer sidebar (like conky_)
on the right::

  % ./infinite-image-scroller.py --pos=800xS-0 --spacing=10 --opacity=0.7 \
      --wm-hints='stick keep_below skip_taskbar skip_pager -accept_focus -decorated' \
      --wm-type-hints=utility --queue=8:0.8 --auto-scroll=10:0.2 -- /mnt/images/

Or borderless window on whole second monitor::

  % ./infinite-image-scroller.py -p M2 -x=-decorated -a 10:0.05 /mnt/images/

(transparency options should only work with compositing WMs though)

See ``./infinite-image-scroller.py --help`` for full list of available options.

.. _conky: https://en.wikipedia.org/wiki/Conky_(software)


Appearance
----------

`GTK3 CSS`_ (e.g. ``~/.config/gtk-3.0/gtk.css``) can be used to style app window
somewhat and also to define new key bindings there.

Full hierarchy of gtk3 widgets used (without "Gtk" prefixes)::

  Window #infinite-image-scroller
    ScrolledWindow
      VBox
        Image
        Image
        ...

(to see tree of these for running app, find all style nodes, tweak stuff on the
fly and such, use GtkInspector_)

Default css just makes backgrounds in all of these transparent, which doesn't affect
opacity of the images, which can be controlled with ``-o/--opacity`` option instead.

For example, to have half-transparent dark-greenish background in the window
(should only be poking-out with ``--spacing`` or non-solid ``--opacity`` settings)::

  #infinite-image-scroller { background: rgba(16,28,16,0.5); }

There isn't much to tweak inside this window in general - just images.

See ``--wm-hints``, ``--wm-type-hints``, ``--icon-name`` and similar options for
stuff related to WM-side decorations like title bar, borders, icon, etc.

.. _GTK3 CSS: https://developer.gnome.org/gtk3/stable/theming.html
.. _GtkInspector: https://wiki.gnome.org/Projects/GTK%2B/Inspector


Configuration File(s)
---------------------

Script will load any "infinite-image-scroller.ini" configuration file(s) from
any of the $XDG_CONFIG_DIRS, $XDG_CONFIG_HOME, ``~/.config`` directories,
or any files specified with ``-c/--conf`` option directly, in that order.

All sections and parameters in these are optional.
Values in later files will override earlier ones.

Special "-" (dash) value can be used to disable looking up configs in any
of the default dirs above, and only use specified one(s) and cli options.

Run script with ``--conf-dump`` option to print resulting configuration
(after loading all existing/specified files), or ``--conf-dump-defaults``
to see default configuration.

Command-line parameters always override config files.


Key bindings
------------

Default keybindings are:

- Arrow keys, Page Up/Down, WSAD - scroll.
- Esc, q, ctrl+q, ctrl+w - quit.
- p, space - pause.
- n, m - slow down, speed up.

Some key/mouse bindings can be added/changed via GTK3 CSS,
same as per "Appearance" section above - look there for details.

Example - add Vi keybindings for scrolling in this window
(append this to e.g. ``~/.config/gtk-3.0/gtk.css``)::

  @binding-set image-scroller-keys {
    bind "k" { "scroll-child" (step-up, 0) };
    bind "j" { "scroll-child" (step-down, 0) };
    bind "h" { "scroll-child" (step-left, 1) };
    bind "l" { "scroll-child" (step-right, 1) };
  }

  #infinite-image-scroller scrolledwindow {
    -gtk-key-bindings: image-scroller-keys;
  }

Other non-window keys can be changed via ini configuration file,
in ``[keys]`` section.

Mouse clicks print image paths to stdout by default.
Format of those lines can be set via "click-print-format" ini option,
or empty value there will disable this output.


Image processing
----------------

When using ``-b/--brightness`` and ``-B/--brightness-adapt`` options to apply
pixel-level processing to images, small helper pixbuf_proc.so C-API module
implementing that has to be compiled::

  gcc -O2 -fpic --shared `python3-config --includes` \
    `pkg-config --libs --cflags gtk+-3.0` pixbuf_proc.c -o pixbuf_proc.so

Can be left in the same dir as the main script or PYTHONPATH anywhere.

Not using PIL/pillow module because simple R/G/B multiplication it uses for this
stuff was very slow/suboptimal, and python GIL prevents using background threads
for such processing.


Performance
-----------

When scrolling large-enough images, synchronous loading (esp. from
non-local filesystem) and resizing (for high-res pics in particular)
can cause stuttering, blocking GUI operation while it happens.

Bundled pixbuf_proc.so helper module tries to address that as well,
by loading/scaling images in a separate background non-GIL-locked threads,
and will be auto-imported if it's available.

See `Image processing`_ section above for how to build it.


Potential TODOs
---------------

- Click-and-drag scrolling.

- Some popup menu (e.g. on right-click) for options maybe.

- Load stuff when manually scrolling in either direction, not just one.

- 2d grid layout mode.
