import localFont from 'next/font/local';

// Plus Jakarta Sans autoalojada (variable, subset latin, 200-800).
//
// Antes venia de next/font/google, que descarga los woff2 en cada build con
// URLs precalculadas dentro de la version instalada de Next. El 2026-08-15
// Google roto esos hashes (v12) y todos los builds pasaron a fallar con 404
// aunque el codigo no hubiera cambiado. Autoalojarla elimina la dependencia
// de red del build de raiz.
export const jakartaSans = localFont({
  src: [
    {
      path: './PlusJakartaSans-Variable.woff2',
      weight: '200 800',
      style: 'normal',
    },
    {
      path: './PlusJakartaSans-Italic.woff2',
      weight: '200 800',
      style: 'italic',
    },
  ],
  display: 'swap',
});
