=======================
Infinite Image Scroller
=======================
------------------------------------------------------------------
 Python3/Gtk3 script to scroll images endlessly across the window
------------------------------------------------------------------

Script loops through all specified image files/dirs, resizes each to window
width/height (preserving aspect ratio) and scrolls them one after another,
i.e. concatenated into one endless "image feed".

``--auto-scroll`` option allows slideshow-like behavior, but otherwise one can
scroll through these manually.

Needs Python-3.x and `PyGObject <http://live.gnome.org/PyGObject>`_ to run.

Aimed to be rather simple and straightforward.


Usage examples
--------------

Simple usage::

	% ./infinite-image-scroller.py path/to/my-image-dir
	% ./infinite-image-scroller.py image1.jpg image2.jpg image3.jpg

Can also read a list or an endless feed of paths (files/dirs) from a
newline-separated list-file or stdin::

	% find -name '*.jpg' | shuf | ./infinite-image-scroller.py -f -
	% ./infinite-image-scroller.py -f carousel.list --auto-scroll 10:0.1

``-a/--auto-scroll`` option takes ``px[:seconds]`` parameter for scrolling
"step" and how often it is repeated (default is 1 second, if omitted), i.e. ``-a
10:0.1`` means "scroll by 10px every 0.1 seconds".

See ``./infinite-image-scroller.py --help`` for full list of available options.


TODO
----

- Option for a horizontal scrolling instead of vertical, and maybe 2d grid,
  reverse direction.

- Options for window position, size, type, border and misc WM hints.

- Random/shuffle/loop options.

- Configuration for hardcoded defaults like vbox_spacing, scroll_delay,
  queue_size, etc.
