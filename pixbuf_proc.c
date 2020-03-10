// Python C-API module to modify
//  image buffer in-place for brightness and such adjustments.
//
// Build with:
//  gcc -O2 -fpic --shared $(python3-config --includes) \
//    pixbuf_proc.c -o pixbuf_proc.so
// Usage:
//  import pixbuf_proc
//  pixbuf_proc.brightness_set(buff, 1.5)
//

#define __STDC_WANT_LIB_EXT2__ 1
#include <stdio.h>

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

static PyObject *
pp_brightness_set(PyObject *self, PyObject *args) {
	Py_buffer img; double k;
	if (!PyArg_ParseTuple(args, "y*d", &img, &k)) return NULL;
	PyObject *res = NULL;

	if (k < 0) {
		char *err; int i = asprintf( &err,
			"Brightness coefficient cannot be negative: %f", k );
		PyErr_SetString(PyExc_ValueError, err);
		goto end; }
	if (!PyBuffer_IsContiguous(&img, 'C')) { // not sure if it ever happens
		PyErr_SetString( pp_error,
			"BUG - cannot process bytes object, as it's not contiguous in memory" );
		goto end; }

	double r, g, b, h, s, p;
	unsigned char *buff = img.buf;
	unsigned char *end = buff + img.len;
	while (buff < end) {
		r = buff[0]; g = buff[1]; b = buff[2];
		RGBtoHSP(r, g, b, &h, &s, &p);
		p *= k;
		HSPtoRGB(h, s, p, &r, &g, &b);
		buff[0] = r; buff[1] = g; buff[2] = b;
		buff += 3; }
	res = Py_None;

	end:
	PyBuffer_Release(&img);
	return res;
}


// Python C-API boilerplate

static PyMethodDef pp_methods[] = {
	{"brightness_set", pp_brightness_set, METH_VARARGS,
		"(buffer, k) Loop over specified image-pixel-buffer,"
			" applying HSP brightness adjustment to each pixel in there."},
	{NULL, NULL, 0, NULL}
};

static struct PyModuleDef pp_module = {
	PyModuleDef_HEAD_INIT,
	"pixbuf_proc",
	"Fast processing for Gdk.pixbuf.get_pixels() buffers.",
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
