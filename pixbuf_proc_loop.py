#!/usr/bin/env python

import os, sys, threading, time, datetime as dt, operator as op
import pixbuf_proc as pp


def image_pixbuf_proc_thread(count, image_files):
	w, h, interp_type, = 1920, 1080, 2 # 2=BILINEAR
	br_adj, br_adj_adapt, br_adj_dir = 1.0, 0, 0
	while True:
		for path in image_files:
			buff, w, h, rs, alpha = pp.process_image_file(
				path, w, h, interp_type, br_adj, br_adj_adapt, br_adj_dir )
			count[0] += 1


def run_proc_loop(image_files, stop_after, report_interval):
	proc_stat_file = open('/proc/self/stat')
	proc_stat_fields = op.itemgetter(13, 14, 23, 22)
	proc_stat_rss_page_bytes = os.sysconf(os.sysconf_names['SC_PAGE_SIZE'])
	proc_stat_jiffies_per_sec = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
	def get_resource_usage():
		proc_stat_file.seek(0)
		try:
			ru = list( int(n) for n in
				proc_stat_fields(proc_stat_file.read().strip().split()) )
			for n in 0, 1: ru[n] /= proc_stat_jiffies_per_sec
			ru[2] *= proc_stat_rss_page_bytes
			return ru
		except IndexError: return None

	ru0_user = ru0_sys = ru0_rss = ru0_vss = 0
	def print_resource_usage():
		ru = get_resource_usage()
		if not ru: return
		ru_user, ru_sys, ru_rss, ru_vss = ru
		ru_user, ru_sys = ru_user - ru0_user, ru_sys - ru0_sys
		ru_rss_diff, ru_vss_diff = ru_rss - ru0_rss, ru_vss - ru0_vss
		ru_rss, ru_vss, ru_rss_diff, ru_vss_diff = (
			v/2**20 for v in [ru_rss, ru_vss, ru_rss_diff, ru_vss_diff] )
		print(
			f'  cpu={ru_user+ru_sys:,.1f}s [user={ru_user:,.1f} sys={ru_sys:,.1f}]'
				f' mem-rss={ru_rss:,.1f}M [{ru_rss_diff:+,.1f}M]'
				f' mem-vss={ru_vss:,.1f}M [{ru_vss_diff:+,.1f}M]\n' )

	image_count, threads = [0], list()
	for n in range(os.cpu_count()):
		threads.append(threading.Thread(
			name=f'pixbuf_proc.{n}', daemon=True,
			target=image_pixbuf_proc_thread, args=[image_count, image_files] ))
	for t in threads: t.start()

	n, ts0 = 0, time.monotonic()
	print( 'Started image-processing loop:'
		f' images={len(image_files)} threads={len(threads)}'
		f' report-interval={report_interval:,.0f}s stop-after={stop_after:,.0f}s\n' )

	while True:
		try:
			time.sleep(report_interval)
			td = time.monotonic() - ts0
		except KeyboardInterrupt: td = stop_after
		if not ru0_user: ru0_user, ru0_sys, ru0_rss, ru0_vss = get_resource_usage()
		print( f'Processing report: n={n}'
			f' images={image_count[0]:,.0f} time=[{dt.timedelta(seconds=td)}]' )
		print_resource_usage()
		if td >= stop_after: break
		n += 1


def main(args=None):
	import argparse
	parser = argparse.ArgumentParser(
		description='Run pixbuf_proc.so processing on specified images in a loop.' )
	parser.add_argument('image_file', nargs='+', help='Image file path(s) to loop over.')
	parser.add_argument('-t', '--stop-after',
		type=float, metavar='seconds', default=120,
		help='Seconds to stop the loop after. Default: %(default)s')
	parser.add_argument('-r', '--report-interval',
		type=float, metavar='seconds', default=10,
		help='Interval in seconds between printing'
			' processing and resource usage reports. Default: %(default)s')
	opts = parser.parse_args(sys.argv[1:] if args is None else args)

	run_proc_loop(opts.image_file, opts.stop_after, opts.report_interval)

if __name__ == '__main__': sys.exit(main())
