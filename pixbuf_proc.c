//
// Python C-API module to modify
//  image buffer in-place for brightness and such adjustments.
//
// Build with:
//  gcc -O2 -fpic --shared `python3-config --includes` \
//    `pkg-config --cflags gtk+-3.0` pixbuf_proc.c -o pixbuf_proc.so
//
// Usage:
//  import pixbuf_proc
//  buff, w, h, rs, alpha = pixbuf_proc\
//    .process_image_file(path, max_w, max_h, scale_interp, brightness_k)
//  pb = GdkPixbuf.Pixbuf.new_from_data(
//    buff, GdkPixbuf.Colorspace.RGB, alpha, 8, w, h, rs )
//

#define __STDC_WANT_LIB_EXT2__ 1
#include <stdio.h>

#include "gdk-pixbuf/gdk-pixbuf.h"

#define PY_SSIZE_T_CLEAN
#include <Python.h>


// RGB<->HSP code from http://alienryderflex.com/hsp.html

#define RGB_clamp(v) v <= 255 ? v : 255;

#define Pr .299
#define Pg .587
#define Pb .114

void RGBtoHSP(
		double R, double G, double B,
		double *H, double *S, double *P ) {
	*P=sqrt(R*R*Pr+G*G*Pg+B*B*Pb);
	if (R==G && R==B) { *H=0.; *S=0.; return; }
	if (R>=G && R>=B) { // R is largest
		if (B>=G) { *H=6./6.-1./6.*(B-G)/(R-G); *S=1.-G/R; }
		else { *H=0./6.+1./6.*(G-B)/(R-B); *S=1.-B/R; } }
	else if (G>=R && G>=B) { // G is largest
		if (R>=B) { *H=2./6.-1./6.*(R-B)/(G-B); *S=1.-B/G; }
		else { *H=2./6.+1./6.*(B-R)/(G-R); *S=1.-R/G; } }
	else { // B is largest
		if (G>=R) { *H=4./6.-1./6.*(G-R)/(B-R); *S=1.-R/B; }
		else { *H=4./6.+1./6.*(R-G)/(B-G); *S=1.-G/B; } } }

void HSPtoRGB(
		double H, double S, double P,
		double *R, double *G, double *B ) {
	double part, minOverMax=1.-S ;
	if (minOverMax>0.) {
		if ( H<1./6.) { // R>G>B
			H= 6.*( H-0./6.); part=1.+H*(1./minOverMax-1.);
			*B=P/sqrt(Pr/minOverMax/minOverMax+Pg*part*part+Pb);
			*R=(*B)/minOverMax; *G=(*B)+H*((*R)-(*B)); }
		else if ( H<2./6.) { // G>R>B
			H= 6.*(-H+2./6.); part=1.+H*(1./minOverMax-1.);
			*B=P/sqrt(Pg/minOverMax/minOverMax+Pr*part*part+Pb);
			*G=(*B)/minOverMax; *R=(*B)+H*((*G)-(*B)); }
		else if ( H<3./6.) { // G>B>R
			H= 6.*( H-2./6.); part=1.+H*(1./minOverMax-1.);
			*R=P/sqrt(Pg/minOverMax/minOverMax+Pb*part*part+Pr);
			*G=(*R)/minOverMax; *B=(*R)+H*((*G)-(*R)); }
		else if ( H<4./6.) { // B>G>R
			H= 6.*(-H+4./6.); part=1.+H*(1./minOverMax-1.);
			*R=P/sqrt(Pb/minOverMax/minOverMax+Pg*part*part+Pr);
			*B=(*R)/minOverMax; *G=(*R)+H*((*B)-(*R)); }
		else if ( H<5./6.) { // B>R>G
			H= 6.*( H-4./6.); part=1.+H*(1./minOverMax-1.);
			*G=P/sqrt(Pb/minOverMax/minOverMax+Pr*part*part+Pg);
			*B=(*G)/minOverMax; *R=(*G)+H*((*B)-(*G)); }
		else { // R>B>G
			H= 6.*(-H+6./6.); part=1.+H*(1./minOverMax-1.);
			*G=P/sqrt(Pr/minOverMax/minOverMax+Pb*part*part+Pg);
			*R=(*G)/minOverMax; *B=(*G)+H*((*R)-(*G)); } }
	 else {
		 if ( H<1./6.) { // R>G>B
			 H= 6.*( H-0./6.); *R=sqrt(P*P/(Pr+Pg*H*H)); *G=(*R)*H; *B=0.; }
		 else if ( H<2./6.) { // G>R>B
			 H= 6.*(-H+2./6.); *G=sqrt(P*P/(Pg+Pr*H*H)); *R=(*G)*H; *B=0.; }
		 else if ( H<3./6.) { // G>B>R
			 H= 6.*( H-2./6.); *G=sqrt(P*P/(Pg+Pb*H*H)); *B=(*G)*H; *R=0.; }
		 else if ( H<4./6.) { // B>G>R
			 H= 6.*(-H+4./6.); *B=sqrt(P*P/(Pb+Pg*H*H)); *G=(*B)*H; *R=0.; }
		 else if ( H<5./6.) { // B>R>G
			 H= 6.*( H-4./6.); *B=sqrt(P*P/(Pb+Pr*H*H)); *R=(*B)*H; *G=0.; }
		 else { // R>B>G
			 H= 6.*(-H+6./6.); *R=sqrt(P*P/(Pr+Pb*H*H)); *B=(*R)*H; *G=0.; } }
	*R = RGB_clamp(*R); *G = RGB_clamp(*G); *B = RGB_clamp(*B); }


static PyObject *pp_error;

void pp_brightness( unsigned char *buff,
		unsigned int buff_len, double k, int alpha ) {
	if (k == 1.0) return;
	double r, g, b, h, s, p;
	unsigned char *end = buff + buff_len;
	while (buff < end) {
		r = buff[0]; g = buff[1]; b = buff[2];
		RGBtoHSP(r, g, b, &h, &s, &p);
		p *= k;
		HSPtoRGB(h, s, p, &r, &g, &b);
		buff[0] = r; buff[1] = g; buff[2] = b;
		buff += alpha ? 4 : 3; }
}

static PyObject *
pp_process_image_file(PyObject *self, PyObject *args) {
	char *path; int w, h, scale_interp; double brightness_k;
	if (!PyArg_ParseTuple( args, "siiid",
		&path, &w, &h, &scale_interp, &brightness_k )) return NULL;

	char *err = NULL; int err_n;

	GError *gerr = NULL;
	GdkPixbuf *pb = NULL, *pb_old = NULL;

	PyObject *res = NULL;
	int pb_w, pb_h, pb_rs, pb_alpha;
	unsigned char *buff = NULL; unsigned int buff_len;

	if (brightness_k < 0) {
		err_n = asprintf(&err, "Brightness cannot be negative: %f", brightness_k);
		PyErr_SetString(PyExc_ValueError, err);
		return NULL; }

	Py_BEGIN_ALLOW_THREADS // -- no python stuff beyond this point

	pb = gdk_pixbuf_new_from_file(path, &gerr);
	if (!pb) {
		err_n = asprintf(&err, "GdkPixbuf image load error - %s", gerr->message);
		g_error_free(gerr);
		goto end; }
	if (gdk_pixbuf_get_colorspace(pb) != GDK_COLORSPACE_RGB) {
		err = "incorrect GdkPixbuf colorspace";
		goto end; }

	pb_w = gdk_pixbuf_get_width(pb);
	pb_h = gdk_pixbuf_get_height(pb);
	pb_alpha = gdk_pixbuf_get_has_alpha(pb);
	if (w <= 0 && h <= 0) { w = pb_w; h = pb_h; }
	else if (w <= 0) w = pb_w * (double) h / (double) pb_h;
	else if (h <= 0) h = pb_h * (double) w / (double) pb_w;
	pb_rs = pb_w * pb_h > w * h; // rescale before pixel processing

	if (pb_rs) {
		buff = gdk_pixbuf_get_pixels_with_length(pb, &buff_len);
		pp_brightness(buff, buff_len, brightness_k, pb_alpha); }

	if (pb_w != w || pb_h != h) {
		pb_old = pb; pb_w = w; pb_h = h;
		pb = gdk_pixbuf_scale_simple(pb_old, w, h, scale_interp);
		g_object_unref(pb_old);
		if (!pb) { err = "GdkPixbuf scaling error"; buff = NULL; goto end; }
		buff = gdk_pixbuf_get_pixels_with_length(pb, &buff_len); }

	if (!pb_rs) {
		if (!buff) buff = gdk_pixbuf_get_pixels_with_length(pb, &buff_len);
		pp_brightness(buff, buff_len, brightness_k, pb_alpha); }

	pb_rs = gdk_pixbuf_get_rowstride(pb);

	end:
	Py_END_ALLOW_THREADS // -- python stuff allowed again

	if (buff) res = Py_BuildValue( "(y#iiib)",
		buff, buff_len, pb_w, pb_h, pb_rs, pb_alpha );
	if (err) PyErr_SetString(pp_error, err);
	if (pb) g_object_unref(pb);

	return res;
}


// Python C-API boilerplate

static PyMethodDef pp_methods[] = {
	{"process_image_file", pp_process_image_file, METH_VARARGS,
		"process_image_file(path, max_w, max_h, scale_interp, brightness_k)"
			" -> (buff, w, h, rs, alpha) - Load image and scale/process it."},
	{NULL, NULL, 0, NULL}
};

static struct PyModuleDef pp_module = {
	PyModuleDef_HEAD_INIT,
	"pixbuf_proc",
	"Background GdkPixbuf image loading and processing.",
	-1,
	pp_methods
};

PyMODINIT_FUNC PyInit_pixbuf_proc(void) {
	PyObject *m = PyModule_Create(&pp_module);
	if (!m) return NULL;

	pp_error = PyErr_NewException("pixbuf_proc.error", NULL, NULL);
	Py_INCREF(pp_error);
	PyModule_AddObject(m, "error", pp_error);

	return m;
}
