const fs = require('fs');
const html = fs.readFileSync('/home/nixos/projects/nixos-ai/tools/lab-timeline/index.html', 'utf8');
const m = html.match(/const MACH_STAGES=(\[.*?\]);/s);
const stages = Function('return ' + m[1])();
// pega todos os scripts pequenos; o da view 2D contem "function machDetail"
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x => x[1]);
const src = scripts.find(x => x.includes('function machDetail(') && x.includes('drawMachine('));
if (!src) throw new Error('script da view 2D nao encontrado');
const els = {};
function el(id) { return els[id] ||= { id, innerHTML:'', textContent:'', max:0, value:'', addEventListener(){} }; }
global.document = { getElementById: el, querySelectorAll: () => [] };
global.window = {};
eval(src);
machDetail('beta', stages[stages.length - 1], 3); // nivel 3 revela auditoria/REAL
const d = els.machDetail.innerHTML;
console.log(JSON.stringify({ bytes: d.length, auditoria: d.includes('Auditoria 28/11'), betaAprendivel: d.includes('aprendiveis'), realBadge: d.includes('REAL') }));
if (!d.includes('Auditoria 28/11') || !d.includes('aprendiveis')) process.exit(2);
