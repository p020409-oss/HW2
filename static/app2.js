const $ = s => document.querySelector(s);
const today = new Date().toISOString().slice(0, 10);
let foods = [], imagePath = "", rangeDays = 1;
$('#meal-date').value = today;

function toast(message) {
  const node = $('#toast'); node.textContent = message; node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 2800);
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw Error(body.detail || '요청을 처리하지 못했습니다.');
  return body;
}
function selectedFood() { return foods.find(food => food.name === $('#menu').value); }
function fillFood() {
  const food = selectedFood(); if (!food) return;
  for (const key of ['kcal', 'carbs', 'protein', 'fat']) $('#' + key).value = food[key];
  $('#source').textContent = `기준량 ${food.portion} · ${food.source}`;
}
async function init() {
  try {
    const data = await api('/api/foods'); foods = data.foods;
    $('#menu').innerHTML = '<option value="">메뉴를 골라주세요</option>' + foods.map(food => `<option>${food.name}</option>`).join('');
    const version = await api('/api/version');
    $('#hint').textContent = version.model_loaded ? `사진을 분석하면 비슷한 메뉴 후보를 보여드려요 · ${version.model_version}` : '사진 분석 모델을 불러오지 못했습니다.';
    await loadDash();
  } catch (error) { toast(error.message); }
}
$('#photo').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 8 * 1024 * 1024) {
    toast('JPG, PNG, WEBP 이미지(8MB 이하)만 올릴 수 있습니다.'); event.target.value = ''; return;
  }
  $('#preview').src = URL.createObjectURL(file); $('#preview').hidden = false;
  $('#hint').textContent = '사진을 분석하고 있습니다…';
  try {
    const form = new FormData(); form.append('file', file);
    const data = await api('/api/analyze', { method: 'POST', body: form });
    imagePath = data.image; $('#menu').value = data.choices[0]?.menu || ''; fillFood();
    const alternatives = data.choices.map(item => `${item.menu} ${item.similarity_score}점`).join(' · ');
    $('#hint').textContent = `${data.note} 후보: ${alternatives}`;
    toast('메뉴 후보를 준비했습니다. 내용을 확인해 주세요.');
  } catch (error) { $('#hint').textContent = error.message; toast(error.message); }
};
$('#menu').onchange = fillFood;
$('#save').onclick = async () => {
  try {
    await api('/api/meals', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: $('#meal-date').value, menu: $('#menu').value, image: imagePath || null,
        ...Object.fromEntries(['kcal', 'carbs', 'protein', 'fat'].map(key => [key, Number($('#' + key).value)])) }) });
    toast('식단을 저장했습니다.'); await loadDash();
  } catch (error) { toast(error.message); }
};
$('#save-goal').onclick = async () => {
  try {
    await api('/api/goals', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: $('#meal-date').value,
        ...Object.fromEntries(['kcal', 'carbs', 'protein', 'fat'].map(key => [key, Number($('#g-' + key).value)])) }) });
    toast('하루 목표를 저장했습니다.'); await loadDash();
  } catch (error) { toast(error.message); }
};
document.querySelectorAll('.tabs button').forEach(button => button.onclick = () => {
  document.querySelector('.tabs .active').classList.remove('active'); button.classList.add('active');
  rangeDays = Number(button.dataset.days); $('#chart-title').textContent = rangeDays === 1 ? '오늘 섭취량' : '최근 7일 섭취량'; loadDash();
});
$('#meal-date').onchange = loadDash;
async function loadDash() {
  try {
    const data = await api(`/api/dashboard?start=${$('#meal-date').value}&days=${rangeDays}`);
    const values = data.days.map(day => day.totals.kcal);
    const goals = data.days.map(day => day.goal?.kcal || Number($('#g-kcal').value));
    const max = Math.max(...values, ...goals, 1);
    $('#chart').innerHTML = data.days.map((day, index) => `<div class="bar-col"><div class="bar-track"><i class="bar-target" style="bottom:${Math.min(100, goals[index] / max * 100)}%"></i><div class="bar-fill" style="height:${Math.min(100, values[index] / max * 100)}%"></div></div><small>${rangeDays === 1 ? '오늘' : day.date.slice(5)}</small></div>`).join('');
    const chosen = data.days.at(-1);
    $('#meal-list').textContent = chosen.meals.length ? chosen.meals.map(meal => `${meal.menu} · ${meal.kcal} kcal`).join('   /   ') : '아직 기록이 없습니다. 첫 메뉴를 기록해 보세요.';
  } catch (error) { toast(error.message); }
}
init();
