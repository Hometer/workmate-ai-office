import test from 'node:test';
import assert from 'node:assert/strict';
import { citationFacts, renderChartSummary, renderMarkdown, renderReportDocument } from '../workmate/static/report-view.js';

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

test('chart amounts preserve full values, zero, negatives, units and recorded scope', () => {
  const render = (value, unit = 'USD') => renderChartSummary('charts/trend.png', [{id:'total_sales',label:'总销售额',value,unit,range:'2026-09-21 至 2026-09-27'}]);
  assert.match(render(123456788912), /123,456,788,912\.00 USD/);
  assert.match(render(0), /0\.00 USD/);
  assert.match(render(-25.125), /-25\.125 USD/);
  assert.match(render(3, null), /3\.00 单位待确认/);
  assert.match(render(3), /2026-09-21 至 2026-09-27/);
  assert.match(render(3), /data-citation="total_sales"/);
  assert.match(render(3), /逐日数值可放大查看原图/);
  for (const value of [null, undefined, '12', Infinity, NaN]) assert.match(render(value), /总销售额待确认/);
});

test('channel facts are already percentages, and zero is a known value', () => {
  const html = renderChartSummary('charts/channel.png', [{id:'channel_share',label:'渠道占比',value:{线上:87.58,线下:12.42,暂未销售:0,未知:null,无穷值:Infinity,负数:-2,超出范围:105}}]);
  assert.match(html, /线上 · <strong>87\.58%<\/strong>/);
  assert.match(html, /线下 · <strong>12\.42%<\/strong>/);
  assert.match(html, /暂未销售 · <strong>0%<\/strong>/);
  assert.match(html, /负数 · <strong>-2%<\/strong>/);
  assert.match(html, /超出范围 · <strong>105%<\/strong>/);
  assert.match(html, /占比含负值或超过 100%，请结合原始数据与计算口径核对/);
  assert.doesNotMatch(html, /8,758|8758|1,242|1242/);
  assert.equal((html.match(/占比待确认/g)||[]).length, 2);
  assert.match(html, /data-citation="channel_share"/);
});

test('Top5 preserves known rank names without inventing amounts', () => {
  const html = renderChartSummary('charts/top5.png', [{id:'top5',label:'Top5 商品',value:['茶具','咖啡杯']}]);
  assert.match(html, /<ol><li>茶具<\/li><li>咖啡杯<\/li><\/ol>/);
  assert.match(html, /各商品的销售金额可放大查看原图/);
  assert.doesNotMatch(html, /销售额：|¥|元|<strong>/);
  const invalid = renderChartSummary('charts/top5.png', [{id:'top5',value:[{name:'茶具',sales:999}]}]);
  assert.match(invalid, /排名待确认或不适用/);
  assert.doesNotMatch(invalid, /999/);
});

test('missing, empty, ambiguous or unavailable chart facts cannot become invented summaries', () => {
  for (const facts of [undefined, null, [], [{id:'top5',value:[]}], [{id:'channel_share',value:{}}]]) {
    for (const name of ['charts/trend.png','charts/top5.png','charts/channel.png']) assert.match(renderChartSummary(name,facts), /待确认/);
  }
  const duplicate = renderChartSummary('charts/trend.png', [{id:'total_sales',value:100},{id:'total_sales',value:200}]);
  assert.doesNotMatch(duplicate, /data-citation|100|200/);
  assert.match(renderChartSummary('charts/legacy.png',[]), /此图表的摘要待确认/);
});

test('chart fact labels, names, range and units cannot inject HTML', () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const facts = [{id:'total_sales',label:hostile,value:12,unit:hostile,range:hostile},{id:'top5',label:hostile,value:[hostile]},{id:'channel_share',label:hostile,value:{[hostile]:87.58}}];
  for (const name of ['charts/trend.png','charts/top5.png','charts/channel.png']) {
    const html = renderChartSummary(name,facts);
    assert.doesNotMatch(html, /<img|<script/);
    assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
  }
});

test('chart summaries prefer the complete known scope over an abbreviated fact range', () => {
  const facts = [{id:'total_sales',value:100,range:'2026-09-28'}];
  assert.match(renderChartSummary('charts/trend.png',facts,'报告周 2026-09-28 ~ 2026-10-04'), /统计范围：报告周 2026-09-28 ~ 2026-10-04/);
  assert.match(renderChartSummary('charts/trend.png',facts,'  '), /统计范围：2026-09-28<\/p>/);
  assert.match(renderChartSummary('charts/trend.png',facts), /统计范围：2026-09-28<\/p>/);
  const hostile = renderChartSummary('charts/trend.png',facts,'<img src=x onerror="alert(1)">');
  assert.doesNotMatch(hostile, /<img/);
  assert.match(hostile, /统计范围：&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
});
