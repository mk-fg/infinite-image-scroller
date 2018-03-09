=======================
Infinite Image Scroller
=======================
-------------------------------------------------------------
 Python3/Gtk3 desktop app to scroll images across the window
-------------------------------------------------------------

Script loops through all specified image files/dirs, resizes each to window
width/height (preserving aspect ratio) and scrolls them one after another,
i.e. concatenated into one endless "image feed", but loading images only as
they're close to be scrolled into view.

Similar widget/behavior is usually called "image carousel" in web development.

``--auto-scroll`` option allows slideshow-like behavior, but otherwise one can
scroll through these manually.

Needs Python-3.x, `Gtk3 <https://wiki.gnome.org/Projects/GTK%2B>`_ and
`PyGObject <https://wiki.gnome.org/action/show/Projects/PyGObject>`_ to run.
All of these usually come pre-installed on desktop linuxes.

Aimed to be rather simple and straightforward, not a full-fledged image viewer.



Usage
-----

Simple usage example::

  % ./infinite-image-scroller.py path/to/my-image-dir
  % ./infinite-image-scroller.py image1.jpg image2.jpg image3.jpg

Can also read a list or an endless feed of paths (files/dirs) from a
newline-separated list-file or stdin::

  % find -name '*.jpg' | shuf | ./infinite-image-scroller.py -f -
  % ./infinite-image-scroller.py -f carousel.list --auto-scroll 10:0.1

``-a/--auto-scroll`` option takes ``px[:seconds]`` parameter for scrolling
"step" and how often it is repeated (default is 1 second, if omitted), i.e.
``-a 10:0.1`` means "scroll by 10px every 0.1 seconds".

More fancy display options - scrolling transparent 800px
sticky/undecorated/unfocusable/bottom-layer sidebar
(like `conky <https://en.wikipedia.org/wiki/Conky_(software)>`_)
on the right::

  % ./infinite-image-scroller.py --pos=800xS-0 --spacing=10 --opacity=0.7 \
      --wm-hints='stick keep_below skip_taskbar skip_pager -accept_focus -decorated' \
      --wm-type-hints=utility --queue=8:0.8 --auto-scroll=10:0.2 -- /mnt/images/

Or borderless window on whole second monitor::

  % ./infinite-image-scroller.py -p M2 -x=-decorated -a 10:0.05 /mnt/images/

(transparency options should only work with compositing WM though)

See ``./infinite-image-scroller.py --help`` for full list of available options.


Appearance
``````````

`Gtk3 CSS <https://developer.gnome.org/gtk3/stable/chap-css-overview.html>`_
(e.g. ``~/.config/gtk-3.0/gtk.css``) can be used to style app window somewhat
and also to define new key bindings there.

Full hierarchy of gtk3 widgets used (without "Gtk" prefixes)::

  Window #infinite-image-scroller
    ScrolledWindow
      VBox
        Image
        Image
        ...

(to see tree of these for running app, find all style nodes, tweak stuff on the
fly and such, use `Gtk-Inspector <https://wiki.gnome.org/Projects/GTK%2B/Inspector>`_)

Default css just makes backgrounds in all of these transparent, which doesn't affect
opacity of the images, which can be controlled with ``-o/--opacity`` option instead.

For example, to have half-transparent dark-greenish background in the window
(should only be poking-out with ``--spacing`` or non-solid ``--opacity`` settings)::

  #infinite-image-scroller { background: rgba(16,28,16,0.5); }

There isn't much to tweak inside this window in general - just images.

See ``--wm-hints``, ``--wm-type-hints``, ``--icon-name`` and similar options for
stuff related to WM-side decorations like title bar, borders, icon, etc.


Key bindings
````````````

Default keybindings are:

- Arrow keys, Page Up/Down, WSAD - scroll.
- Esc, q, ctrl+q, ctrl+w - quit.

Key/mouse bindings can be added/changed via Gtk3 CSS, same as per "Appearance"
section above - look there for details.

Example - add Vi keybindings for scrolling in this window (append this to
e.g. ``~/.config/gtk-3.0/gtk.css``)::

  @binding-set image-scroller-keys {
    bind "k" { "scroll-child" (step-up, 0) };
    bind "j" { "scroll-child" (step-down, 0) };
    bind "h" { "scroll-child" (step-left, 1) };
    bind "l" { "scroll-child" (step-right, 1) };
  }

  #infinite-image-scroller scrolledwindow {
    -gtk-key-bindings: image-scroller-keys;
  }



TODO
----

- Option for a horizontal scrolling instead of vertical, maybe 2d grid,
  reverse direction.

- Random/shuffle/loop options.

- Some popup menu (e.g. on right-click) for options maybe.

- Load stuff when scrolling in either direction, not just one.

- More keybindings - scroll to next image, linger on one image, pause.
