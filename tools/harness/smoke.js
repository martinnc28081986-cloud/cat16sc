/* Chequeo automático ("smoke test") de MI PLANTEL. Se activa con ?smoke=1 en el arnés:
     http://localhost:8125/?as=PROFE&smoke=1
   Espera a que cargue la app, recorre TODAS las pantallas del usuario que entró (profe, coordinador o
   super admin) y junta cualquier error. El resultado queda en window.__smoke y en el título de la
   pestaña ("SMOKE OK profe" / "SMOKE FALLA profe"). */
(async function () {
  const problemas = [], pantallas = [];
  const anotar = (donde, msg) => problemas.push(donde + ': ' + String(msg).slice(0, 160));
  window.addEventListener('error', e => anotar('error', e.message));
  window.addEventListener('unhandledrejection', e => anotar('promesa sin atender', (e.reason && e.reason.message) || e.reason));
  const warn = console.warn;
  console.warn = (...a) => {
    const t = a.map(x => (x && x.message) || String(x)).join(' ');
    // Los avisos que la app misma emite cuando algo falla
    if (/error|no se pudo|before initialization|is not defined/i.test(t)) anotar('aviso de consola', t);
    warn.apply(console, a);
  };
  const esperar = ms => new Promise(r => setTimeout(r, ms));
  const visible = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
  const texto = id => ((document.getElementById(id) || {}).innerText || '');

  for (let i = 0; i < 80; i++) { await esperar(150); const l = document.getElementById('loadingScreen'); if (!l || getComputedStyle(l).display === 'none') break; }
  await esperar(2500);

  // Profe con más de una categoría (o profe + coordinador): primero elige a dónde entrar
  const selector = document.getElementById('catSelectorScreen');
  if (visible(selector)) {
    const botones = [...selector.querySelectorAll('button')];
    const primero = botones.find(b => !/coordinaci/i.test(b.textContent)) || botones[0];
    if (primero) primero.click();
    await esperar(3500);
  }

  const rol = visible(document.getElementById('superadmin-app')) ? 'super admin'
            : visible(document.getElementById('coord-app')) ? 'coordinador'
            : visible(document.getElementById('loginScreen')) ? 'sin sesión' : 'profe';
  const revisar = (nombre, cuerpo) => {
    const roto = /No se pudo dibujar|Error:/i.test(cuerpo);
    pantallas.push({ nombre, ok: !roto, muestra: cuerpo.replace(/\s+/g, ' ').slice(0, 60) });
    if (roto) anotar('pantalla ' + nombre, 'no se pudo dibujar: ' + cuerpo.replace(/\s+/g, ' ').slice(0, 90));
  };

  if (rol === 'profe') {
    const recorrido = [['ent','tomar'],['ent','historial'],['ent','stats'],['par','tablas'],['par','cit-stats'],['par','citaciones'],['par','formacion'],['par','pospartido'],['plantel','plantel']];
    for (const [sec, tab] of recorrido) {
      try { window.switchSection(sec); window.switchTab(tab); await esperar(400); revisar(sec + '/' + tab, (document.querySelector('.view.active') || {}).innerText || ''); }
      catch (e) { anotar('pantalla ' + sec + '/' + tab, e.message); }
    }
    // La app tiene que abrir en Entreno
    window.switchSection('ent'); window.switchTab('tomar');
  } else if (rol === 'coordinador') {
    for (const t of ['hoy', 'semana', 'equipos', 'jugadores', 'liga', 'calendario', 'uso']) {
      try { window.coordTab(t); await esperar(600); revisar('coord/' + t, texto('coordVista')); }
      catch (e) { anotar('pantalla coord/' + t, e.message); }
    }
  } else if (rol === 'super admin') {
    for (const t of ['clubes', 'facturacion', 'usuarios', 'uso', 'datos']) {
      try { window.saTab(t); await esperar(900); revisar('sa/' + t, texto('sa-' + t)); }
      catch (e) { anotar('pantalla sa/' + t, e.message); }
    }
  }

  // La página no puede tener scroll horizontal
  const de = document.documentElement;
  // (solo si la ventana tiene ancho: con la ventana oculta el navegador informa 0)
  if (de.clientWidth > 100 && de.scrollWidth > de.clientWidth + 1) anotar('diseño', 'scroll horizontal: ' + de.scrollWidth + ' > ' + de.clientWidth);

  window.__smoke = { rol, ok: problemas.length === 0, problemas, pantallas };
  document.title = (problemas.length ? 'SMOKE FALLA ' : 'SMOKE OK ') + rol;
})();
