import test from 'node:test';
import assert from 'node:assert/strict';
import { fileName, filterTasks, summaryIdentity, reportSection, shareWidth, taskProgress } from '../workmate/static/workspace.js';

test('history searches only the display filename, including Windows paths', () => {
  const tasks = [{ input_file: '/private/客户/SALES.csv', status: 'done' }, { input_file: 'C:\\data\\周报.xlsx', status: 'failed' }];
  assert.equal(fileName(tasks[1].input_file), '周报.xlsx');
  assert.deepEqual(filterTasks(tasks, ' sales ', 'all'), [tasks[0]]);
  assert.deepEqual(filterTasks(tasks, '客户', 'all'), []);
});
test('running filter includes accepted tasks, never failed or unknown states', () => {
  const tasks = ['created', 'running', 'done', 'failed', 'unexpected'].map(status => ({ status }));
  assert.deepEqual(filterTasks(tasks, '', 'running').map(t => t.status), ['created', 'running']);
  assert.deepEqual(filterTasks(tasks, '', 'failed').map(t => t.status), ['failed']);
  assert.equal(filterTasks(tasks, '', 'all').length, 5);
});
test('missing or unvalidated model identity cannot appear verified', () => {
  assert.equal(summaryIdentity(null).kind, 'pending');
  assert.equal(summaryIdentity({ provider: 'ollama', status: 'invalid' }).kind, 'pending');
  assert.equal(summaryIdentity({ provider: 'mock', status: 'passed' }).kind, 'warning');
  assert.equal(summaryIdentity({ provider: 'ollama', status: 'fallback' }).kind, 'warning');
  assert.equal(summaryIdentity({ provider: 'ollama', status: 'passed' }).kind, 'verified');
});
test('report summary preserves citations and stops before the next section', () => {
  assert.equal(reportSection('# 周报\n## 核心结论\n\n销售额 600 USD [total_sales]。\n\n## 关键数字\n其他', '核心结论'), '销售额 600 USD [total_sales]。');
  assert.equal(reportSection('## 核心结论\n事实\n### 子说明\n细节', '核心结论'), '事实\n### 子说明\n细节');
  assert.equal(reportSection(null, '核心结论'), '');
  assert.equal(reportSection('## 关键数字\n600', '核心结论'), '');
});
test('visual share widths are bounded without changing the source value', () => {
  assert.equal(shareWidth(141.8), 100);
  assert.equal(shareWidth(-10), 0);
  assert.equal(shareWidth(87.58), 87.58);
  for (const value of [NaN, Infinity, null, '90', 'url(evil)']) assert.equal(shareWidth(value), 0);
});
test('progress labels follow actual backend steps and do not invent percentages', () => {
  assert.equal(taskProgress({ status: 'created' }), '任务已受理，等待开始');
  assert.equal(taskProgress({ status: 'running', steps: [{ name: 'write_summary', status: 'running' }] }), '正在生成销售摘要');
  assert.equal(taskProgress({ status: 'running', steps: [{ name: 'write_summary', status: 'done' }] }), '正在处理销售周报');
});
