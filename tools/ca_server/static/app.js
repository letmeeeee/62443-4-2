'use strict';
let csrf = '', offset = 0, total = 0, exportId = '', busy = false;
let pendingIssue = null;
const $ = selector => document.querySelector(selector);
function notice(message, error = false) { $('#notice').textContent = message; $('#notice').classList.toggle('error', error); }
async function api(path, options = {}, downloadName = null) {
  const response = await fetch(path, {credentials:'same-origin', ...options,
    headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf, ...(options.headers || {})}});
  if (!response.ok) {
    const result = await response.json().catch(() => ({message:'请求失败：'+response.status}));
    if (response.status === 401 && path !== '/api/login') await bootstrap();
    throw new Error(result.message || '操作失败');
  }
  if (downloadName) {
    const blob = await response.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = downloadName; link.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    return;
  }
  return response.json();
}
function post(path, data = {}, name = null, headers = {}) { return api(path, {method:'POST', body:JSON.stringify(data), headers}, name); }
function values(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const key of ['rsa_bits','days']) if (key in data) data[key] = Number(data[key]);
  for (const key of ['dns_names','ip_addresses']) if (key in data) data[key] = data[key].split(/[,，\s]+/).filter(Boolean);
  if (data.algorithm === 'P-256') delete data.rsa_bits;
  return data;
}
function run(action) {
  return async event => {
    if (event) event.preventDefault();
    if (busy) return;
    busy = true;
    document.querySelector('main').inert = true;
    $('#export-form').inert = true;
    document.body.setAttribute('aria-busy', 'true');
    notice('正在处理…');
    try { await action(event); if ($('#notice').textContent === '正在处理…') notice('操作完成'); }
    catch (error) { notice(error.message, true); }
    finally {
      busy = false;
      document.querySelector('main').inert = false;
      $('#export-form').inert = false;
      document.body.setAttribute('aria-busy', 'false');
    }
  };
}
async function bootstrap() {
  const state = await api('/api/session'); csrf = state.csrf_token;
  $('#login-panel').hidden = state.authenticated; $('#workspace').hidden = !state.authenticated; $('#logout').hidden = !state.authenticated;
  if (state.authenticated) await refresh();
  else notice('请输入初始化时设置的管理员口令。');
}
async function status() {
  const state = await api('/api/ca');
  $('#initialize-panel').hidden = state.initialized;
  $('#unlock-form').hidden = !state.initialized || state.unlocked;
  $('#lock-state').textContent = !state.initialized ? '未初始化' : state.unlocked ? '已解锁' : '已锁定';
  $('#ca-status').textContent = state.initialized ? [state.subject, 'CA 算法：'+state.algorithm+(state.rsa_bits ? ' '+state.rsa_bits : ''),
    'SHA-256：'+state.fingerprint_sha256, '到期：'+new Date(state.expires_at).toLocaleString(),
    'CRL #'+state.crl_number+' · 到期：'+new Date(state.crl_next_update).toLocaleString()+(state.crl_expired ? '（已过期，请更新并重新分发）' : ''),
    state.unlocked ? '解锁剩余：'+state.unlock_seconds_remaining+' 秒' : '签发、私钥导出和吊销前请解锁 CA'].join('\n') : '尚未创建 CA，请先填写下方 CA 信息。';
  for (const id of ['download-ca','download-crl']) $('#'+id).disabled = !state.initialized;
  for (const id of ['refresh-crl','lock-ca','issue-button']) $('#'+id).disabled = !state.unlocked;
}
function actionButton(label, handler) { const button = document.createElement('button'); button.textContent = label; button.onclick = run(handler); return button; }
async function devices() {
  const result = await api('/api/devices?limit=20&offset='+offset); total = result.total;
  $('#devices').replaceChildren();
  for (const item of result.items) {
    const tr = document.createElement('tr');
    const identity = document.createElement('td'); identity.textContent = item.device_id;
    const cn = document.createElement('small'); cn.textContent = item.cn; identity.append(cn); tr.append(identity);
    const expired = new Date(item.expires_at).getTime() <= Date.now();
    for (const value of [item.profile+' / '+item.algorithm+(item.rsa_bits ? ' '+item.rsa_bits : ''), new Date(item.expires_at).toLocaleString(), item.revoked_at ? '已吊销' : expired ? '已过期' : '有效']) {
      const td = document.createElement('td'); td.textContent = value; tr.append(td);
    }
    const actions = document.createElement('td');
    actions.append(actionButton('证书', () => api('/api/devices/'+item.id+'/certificate', {}, 'enc.crt')),
      actionButton('CSR', () => api('/api/devices/'+item.id+'/csr', {}, 'device.csr.pem')));
    if (!item.revoked_at && !expired) {
      actions.append(actionButton('私钥与完整包', () => {
        exportId = item.id; $('#export-form').reset(); $('#export-form').elements.key_format.value = item.profile === 'goose' ? 'plain' : 'encrypted';
        exportMode(); $('#export-dialog').showModal(); notice('请选择私钥导出格式。');
      }));
    }
    if (!item.revoked_at) actions.append(actionButton('吊销', async () => {
      if (!confirm('确认吊销 '+item.cn+'？此操作不可撤回，将立即更新 CRL。')) { notice('已取消'); return; }
      const reason = prompt('吊销原因：key_compromise / superseded / affiliation_changed / cessation_of_operation', 'cessation_of_operation');
      if (!reason) { notice('已取消'); return; }
      await post('/api/devices/'+item.id+'/revoke', {reason}); await refresh(); notice('已吊销。请下载最新 CRL，导入通信双方并应用。');
    }));
    tr.append(actions); $('#devices').append(tr);
  }
  if (!result.items.length) { const tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 5; td.textContent = '暂无签发记录'; tr.append(td); $('#devices').append(tr); }
  $('#page-status').textContent = '共 '+total+' 条 · 第 '+(Math.floor(offset/20)+1)+' 页';
  $('#previous').disabled = offset === 0; $('#next').disabled = offset+20 >= total;
}
async function events() { const result = await api('/api/events'); $('#events').textContent = result.items.map(row => row.time+' · '+row.action+' · '+row.target+' · '+row.ip).join('\n') || '暂无记录'; }
async function refresh() { await status(); await devices(); await events(); notice('数据已更新'); }
function algorithmControls(form) {
  const goose = form.id === 'device-form' && form.elements.profile.value === 'goose';
  if (goose) form.elements.algorithm.value = 'P-256';
  form.elements.algorithm.disabled = goose;
  form.elements.rsa_bits.disabled = form.elements.algorithm.value !== 'RSA';
  if (form.id === 'device-form') for (const key of ['dns_names','ip_addresses']) form.elements[key].disabled = goose;
}
function exportMode() {
  const encrypted = $('#export-form').elements.key_format.value === 'encrypted';
  $('#export-password-label').hidden = !encrypted; $('#export-confirm-label').hidden = !encrypted; $('#plain-note').hidden = encrypted;
  for (const key of ['export_password','export_password_confirm']) { const input = $('#export-form').elements[key]; input.required = encrypted; input.disabled = !encrypted; }
}
$('#login-form').onsubmit = run(async event => {
  const form = event.currentTarget;
  try { const result = await post('/api/login', values(form)); csrf = result.csrf_token; await bootstrap(); }
  finally { form.reset(); }
});
$('#logout').onclick = run(async () => { await post('/api/logout'); await bootstrap(); });
$('#ca-form').onsubmit = run(async event => {
  const form = event.currentTarget, data = values(form);
  if (data.password !== data.password_confirm) throw new Error('两次 CA 口令不一致');
  delete data.password_confirm;
  try { await post('/api/ca', data); form.reset(); await refresh(); notice('CA 已创建。请输入 CA 保护口令解锁后签发。'); }
  finally { form.elements.password.value = ''; form.elements.password_confirm.value = ''; }
});
$('#unlock-form').onsubmit = run(async event => {
  const form = event.currentTarget;
  try { await post('/api/ca/unlock', values(form)); await refresh(); }
  finally { form.reset(); }
});
$('#lock-ca').onclick = run(async () => { await post('/api/ca/lock'); await status(); notice('CA 已锁定'); });
$('#refresh-crl').onclick = run(async () => { await post('/api/ca/crl/refresh'); await refresh(); notice('CRL 已更新，请下载并分发至设备。'); });
$('#download-ca').onclick = run(async () => { await api('/api/ca/certificate', {}, 'ca-roots.crt'); notice('根证书已下载'); });
$('#download-crl').onclick = run(async () => { await api('/api/ca/crl', {}, 'crls.pem'); notice('CRL 已下载'); });
$('#device-form').onsubmit = run(async event => {
  const form = event.currentTarget, data = values(form);
  // Disabled controls are absent from FormData; GOOSE has a fixed algorithm.
  if (data.profile === 'goose') data.algorithm = 'P-256';
  const serialized = JSON.stringify(data);
  if (!pendingIssue || pendingIssue.serialized !== serialized) pendingIssue = {serialized, id:crypto.randomUUID()};
  const result = await post('/api/devices', data, null, {'Idempotency-Key':pendingIssue.id});
  pendingIssue = null; offset = 0; await refresh(); notice('签发成功：'+result.cn+'。可在记录中下载私钥与完整包。');
});
$('#refresh').onclick = run(refresh); $('#events-refresh').onclick = run(events);
$('#previous').onclick = run(async () => { offset = Math.max(0,offset-20); await devices(); notice('记录已更新'); });
$('#next').onclick = run(async () => { offset += 20; await devices(); notice('记录已更新'); });
for (const form of [$('#ca-form'),$('#device-form')]) { form.addEventListener('change', () => algorithmControls(form)); algorithmControls(form); }
$('#export-form').elements.key_format.onchange = exportMode;
$('#export-cancel').onclick = () => { $('#export-form').reset(); $('#export-dialog').close(); };
$('#export-dialog').addEventListener('cancel', () => $('#export-form').reset());
$('#export-form').onsubmit = run(async event => {
  const form = event.currentTarget, data = values(form);
  if (data.key_format === 'encrypted' && data.export_password !== data.export_password_confirm) throw new Error('两次导出口令不一致');
  delete data.export_password_confirm;
  if (data.key_format === 'plain') data.confirm_plaintext = true;
  try { await post('/api/devices/'+exportId+'/export', data, 'device-'+exportId+'.zip'); form.reset(); $('#export-dialog').close(); notice('设备文件包已下载'); }
  finally { form.elements.export_password.value = ''; form.elements.export_password_confirm.value = ''; }
});
bootstrap().catch(error => notice(error.message, true));
setInterval(() => { if (!$('#workspace').hidden && !busy) status().catch(error => notice(error.message,true)); }, 30000);
