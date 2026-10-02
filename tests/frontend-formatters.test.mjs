import test from "node:test";
import assert from "node:assert/strict";
import { formatChangeFact } from "../workmate/static/formatters.js";

test("美元增长使用金额事实单位，并从金额符号判断方向", () => {
  assert.equal(formatChangeFact({name: "线上", delta: 325.5, direction: "减少", contribution_pct: 100}, "USD"),
    "线上：增加 325.5 USD，占总变化 100%");
});

test("下降展示正的幅度，避免减少负金额", () => {
  assert.equal(formatChangeFact({name: "门店", delta: -125.5}, "元"), "门店：减少 125.5 元");
});

test("未提供单位时，各变化金额明确待确认", () => {
  assert.equal(formatChangeFact({name: "线上", delta: 50}), "线上：增加 50 单位待确认");
});

test("条目显式单位优先于历史页面单位", () => {
  assert.equal(formatChangeFact({name: "线上", delta: -10, unit: "EUR"}, "USD"), "线上：减少 10 EUR");
});

test("零变化明确持平，不误标涨跌", () => {
  assert.equal(formatChangeFact({name: "门店", delta: -0}, "USD"), "门店：持平 0 USD");
});

test("非有限或未核实类型不能作为变化金额显示", () => {
  for (const delta of [Infinity, NaN, "50", null]) {
    assert.equal(formatChangeFact({name: "线上", delta, contribution_pct: Infinity}, "USD"),
      "线上：变化金额待确认 USD");
  }
});
