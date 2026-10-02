import test from 'node:test';
import assert from 'node:assert/strict';
import { citationFacts, renderMarkdown, renderReportDocument } from '../workmate/static/report-view.js';

test('citations link exact fact IDs even when different metrics have equal values', () => {
  const facts = [{id:'total_sales',label:'销售额',value:2,unit:'USD'}, {id:'order_count',label:'订单量',value:2,unit:'单'}];
  const html = renderMarkdown('2 USD [total_sales]；2 单 [order_count]。',facts);
  assert.match(html, /data-citation="total_sales" aria-label="查看依据：销售额"/);
  assert.match(html, /data-citation="order_count" aria-label="查看依据：订单量"/);
});
test('missing, ambiguous and unsafe IDs remain visible without actionable links', () => {
  const facts = [{id:'total_sales',label:'一'}, {id:'total_sales',label:'二'}, {id:'bad" onclick="evil',label:'危险'}];
  assert.equal(citationFacts(facts).size,0);
  const html=renderMarkdown('[total_sales] [old_id] [bad" onclick="evil]',facts);
  assert.doesNotMatch(html,/data-citation=/);
  assert.equal((html.match(/依据不可用/g)||[]).length,3);
  assert.match(html,/&quot; onclick=&quot;evil/);
});
test('report HTML and fact labels cannot execute markup', () => {
  const html=renderMarkdown('<script>alert(1)</script> [total_sales]',[{id:'total_sales',label:'"><img src=x onerror=alert(1)>'}]);
  assert.doesNotMatch(html,/<script>|<img/);
  assert.match(html,/&lt;script&gt;/);
  assert.match(html,/aria-label="查看依据：&quot;&gt;&lt;img/);
});
test('references never retain IDs from a previously rendered task', () => {
  assert.match(renderMarkdown('[total_sales]',[{id:'total_sales',label:'旧任务'}]),/data-citation=/);
  assert.doesNotMatch(renderMarkdown('[total_sales]',[]),/data-citation=/);
  assert.match(renderMarkdown('[total_sales]',null),/依据不可用/);
});
test('metadata moves after conclusions without changing or losing source text', () => {
  const md='# 周报\n\n- 单位：待确认\n- 范围：报告周\n\n## 核心结论\n600 USD [total_sales]\n## 限制\n不得外发';
  const html=renderReportDocument(md,[{id:'total_sales',label:'销售额'}]);
  assert.ok(html.indexOf('核心结论')<html.indexOf('统计口径与核对说明'));
  for(const text of ['单位：待确认','范围：报告周','不得外发','600 USD']) assert.ok(html.includes(text));
  assert.ok(md.includes('- 单位：待确认'));
});
test('legacy prose and reports without known sections retain reading order', () => {
  const md='# 旧报告\n必须先看这个限制\n## 数字\n600';
  const html=renderReportDocument(md);
  assert.doesNotMatch(html,/<details/);
  assert.ok(html.indexOf('必须先看')<html.indexOf('<h2>数字'));
  assert.match(renderReportDocument('普通旧文本'),/<p>普通旧文本<\/p>/);
});
