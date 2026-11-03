function u(e){return e>=32768?e-65536:e}function s(e,r){return Object.entries(e).filter(([t])=>n(Number(r),Number(t))).map(([,t])=>t)}const n=(e,r)=>(e&1<<r)!==0;export{s as p,u};
