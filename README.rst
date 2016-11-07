=======================
Infinite Image Scroller
=======================
------------------------------------------------------------------
 Python3/Gtk3 script to scroll images endlessly across the window
------------------------------------------------------------------

Script loops through all specified image files/dirs, resizes each to window
width/height (preserving aspect ratio) and scrolls them one after another,
i.e. concatenated into one endless "image feed", but loading images only as
they're close to be scrolled into view.

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

More fancy display options - scrolling transparent 800px sidebar on the right::

  % ./infinite-image-scroller.py --pos=800xS-0 \
      --spacing=10 --opacity=0.7 --queue=8:0.8 -a 10:0.2 -- /mnt/images/

Transparency options should only work with compositing WM though.

See ``./infinite-image-scroller.py --help`` for full list of available options.


Appearance
``````````

`Gtk3 styles <https://developer.gnome.org/gtk3/stable/chap-css-overview.html>`_
can be used to style app window somewhat.

Full hierarchy of gtk3 widgets used::

  GtkWindow #scroller
    GtkScrolledWindow
      GtkVBox
        Image
        Image
        ...

Default css just makes backgrounds in all of these transparent, which doesn't
affect opacity of the images, which can be controlled with ``-o/--opacity``
option instead.



TODO
----

- Option for a horizontal scrolling instead of vertical, maybe 2d grid,
  reverse direction.

- Options for window type, border and misc other WM hints.

- Random/shuffle/loop options.

- More hotkeys (incl. arrows for scrolling), right-click menu controls maybe.

- Load stuff when scrolling in either direction, not just one.
