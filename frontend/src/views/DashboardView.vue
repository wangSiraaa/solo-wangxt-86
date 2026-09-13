<template>
  <div>
    <div class="section-head">
      <h2>财务总览</h2>
      <span class="muted" v-if="summary">当前期间：{{ summary.current_period }}</span>
    </div>

    <div class="cards" v-if="summary">
      <div class="card">
        <div class="label">签约总额</div>
        <div class="value">{{ fmtMoney(summary.total_price) }}</div>
      </div>
      <div class="card">
        <div class="label">累计开票</div>
        <div class="value">{{ fmtMoney(summary.billed) }}</div>
        <div class="sub">未开票 {{ fmtMoney(summary.unbilled) }}</div>
      </div>
      <div class="card">
        <div class="label">累计收款</div>
        <div class="value">{{ fmtMoney(summary.received) }}</div>
      </div>
      <div class="card">
        <div class="label">已确认收入</div>
        <div class="value" style="color: var(--green)">{{ fmtMoney(summary.recognized) }}</div>
        <div class="sub">未来计划 {{ fmtMoney(summary.planned) }}</div>
      </div>
      <div class="card">
        <div class="label">递延余额(已开票未确认)</div>
        <div class="value" style="color: var(--blue)">{{ fmtMoney(summary.deferred) }}</div>
      </div>
      <div class="card">
        <div class="label">待确认(缺验收证据)</div>
        <div class="value" style="color: var(--amber)">{{ fmtMoney(summary.pending) }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="section-head">
        <h3 style="margin:0">合同清单</h3>
        <span class="formula">签约 ≠ 收款 ≠ 确认；开票不直接构成收入</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>合同号</th><th>客户</th><th>签订日</th>
            <th class="num">签约额</th><th class="num">已开票</th><th class="num">已收款</th>
            <th class="num">已确认</th><th class="num">待确认</th><th class="num">递延余额</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in contracts" :key="c.id" @click="$router.push(`/contracts/${c.id}`)" style="cursor:pointer">
            <td>{{ c.number }}</td>
            <td>{{ c.customer }}</td>
            <td>{{ c.signed_date }}</td>
            <td class="num">{{ fmtMoney(c.totals.total_price) }}</td>
            <td class="num">{{ fmtMoney(c.totals.billed) }}</td>
            <td class="num">{{ fmtMoney(c.totals.received) }}</td>
            <td class="num">{{ fmtMoney(c.totals.recognized) }}</td>
            <td class="num">
              <span v-if="Number(c.totals.pending) > 0" class="badge amber">{{ fmtMoney(c.totals.pending) }}</span>
              <span v-else>0.00</span>
            </td>
            <td class="num">{{ fmtMoney(c.totals.deferred) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="margin-bottom:0">点击行进入合同组成与递延余额对照。</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api";
import { fmtMoney } from "../format";

const summary = ref(null);
const contracts = ref([]);

onMounted(async () => {
  [summary.value, contracts.value] = await Promise.all([api.summary(), api.contracts()]);
});
</script>
