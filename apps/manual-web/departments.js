const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
const api = async (path, method = 'GET', body) => {
  const response = await fetch('/api/v1/manuals/departments' + path, {
    method, headers: {'X-Manual-Request': '1', 'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '保存失败')
  return result
}

const button = document.createElement('button')
button.className = 'quiet'
button.textContent = '部门与资料范围'
document.querySelector('.sidebar').append(button)

const dialog = document.createElement('dialog')
dialog.innerHTML = '<form method="dialog"><button>关闭 ×</button></form><div id="department-content"></div>'
document.body.append(dialog)
const content = dialog.querySelector('#department-content')
let departments = []
let scopes = []

async function render() {
  const filter = content.querySelector('#department-filter')?.value || 'unconfirmed'
  ;[departments, scopes] = await Promise.all([api(''), api('/entries/scopes')])
  const visible = scopes.filter(item => filter === 'all' || (filter === 'unconfirmed' ? !item.confirmed : item.department_ids.includes(filter)))
  content.innerHTML = `<h2>部门与资料范围</h2><p class="note">当前仅保存配置，钉钉检索权限尚未启用。</p>
    <h3>钉钉部门映射与跨部门授权</h3>
    <select id="department-select">${departments.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('')}</select>
    <div id="department-settings"></div>
    <h3>资料适用范围</h3><select id="department-filter"><option value="unconfirmed">待确认</option><option value="all">全部资料</option>${departments.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('')}</select>
    <div class="step"><strong>批量设置选中资料</strong><p class="note">请先核对资料内容，再设置适用范围。</p><label><input type="checkbox" id="batch-company"> 全公司适用</label><div>${departments.map(d => `<label style="display:inline-block;margin:5px"><input type="checkbox" name="batch-dept" value="${d.id}"> ${escapeHtml(d.name)}</label>`).join('')}</div><button type="button" id="save-batch">确认所选资料范围</button></div>
    <div>${visible.map(item => `<section class="step" data-entry-id="${item.entry_id}"><label><input type="checkbox" name="batch-entry" value="${item.entry_id}"> <strong>${escapeHtml(item.title)}</strong></label><p class="note">现有分类 ${escapeHtml(item.category_name || '未分类')} · ${item.confirmed ? '已确认' : '待确认'}</p>
      <label><input type="checkbox" name="company" ${item.company_wide ? 'checked' : ''}> 全公司适用</label>
      <div>${departments.map(d => `<label style="display:inline-block;margin:5px"><input type="checkbox" name="dept" value="${d.id}" ${item.department_ids.includes(d.id) ? 'checked' : ''}> ${escapeHtml(d.name)}</label>`).join('')}</div>
      <button type="button" data-save-scope>确认并保存范围</button></section>`).join('') || '<p>没有匹配的资料。</p>'}</div>`
  content.querySelector('#department-filter').value = filter
  await showSettings()
}

async function showSettings() {
  const department = departments.find(d => d.id === content.querySelector('#department-select').value)
  if (!department) return
  const grants = await api('/' + department.id + '/grants')
  content.querySelector('#department-settings').innerHTML = `<label>钉钉部门 ID <input id="dingtalk-department-id" value="${escapeHtml(department.dingtalk_department_id || '')}"></label>
    <p>允许额外检索的部门</p><div>${departments.filter(d => d.id !== department.id).map(d => `<label style="display:inline-block;margin:5px"><input type="checkbox" name="grant" value="${d.id}" ${grants.includes(d.id) ? 'checked' : ''}> ${escapeHtml(d.name)}</label>`).join('')}</div>
    <button type="button" id="save-department">保存部门设置</button>`
}

function report(error) { alert(error.message) }
button.addEventListener('click', () => { render().then(() => dialog.showModal()).catch(report) })
content.addEventListener('change', event => {
  if (event.target.id === 'department-select') showSettings().catch(report)
  if (event.target.id === 'department-filter') render().catch(report)
})
content.addEventListener('click', event => {
  if (event.target.id === 'save-batch') {
    const entry_ids = [...content.querySelectorAll('[name=batch-entry]:checked')].map(input => input.value)
    const department_ids = [...content.querySelectorAll('[name=batch-dept]:checked')].map(input => input.value)
    const company_wide = content.querySelector('#batch-company').checked
    if (!entry_ids.length) return report(new Error('请先选择资料。'))
    api('/entries/scopes/batch', 'PUT', {entry_ids, scope: {company_wide, department_ids, confirmed: true}})
      .then(render).catch(report)
  }
  if (event.target.id === 'save-department') {
    const id = content.querySelector('#department-select').value
    const value = content.querySelector('#dingtalk-department-id').value.trim() || null
    const target_department_ids = [...content.querySelectorAll('[name=grant]:checked')].map(input => input.value)
    api('/' + id + '/mapping', 'PUT', {dingtalk_department_id: value})
      .then(() => api('/' + id + '/grants', 'PUT', {target_department_ids}))
      .then(() => alert('部门设置已保存。')).catch(report)
  }
  if (event.target.hasAttribute('data-save-scope')) {
    const row = event.target.closest('[data-entry-id]')
    const company_wide = row.querySelector('[name=company]').checked
    const department_ids = [...row.querySelectorAll('[name=dept]:checked')].map(input => input.value)
    api('/entries/' + row.dataset.entryId + '/scope', 'PUT', {company_wide, department_ids, confirmed: true})
      .then(render).catch(report)
  }
})
