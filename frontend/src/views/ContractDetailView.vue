<template>
  <div v-if="c">
    <div class="section-head">
      <h2>{{ c.number }} · {{ c.customer }}</h2>
      <span class="muted">签订于 {{ c.signed_date }} ｜ {{ c.note }}</span>
    </div>

    <div class="cards">
      <div class="card"><div class="label">签约额</div><div class="value">{{ fmtMoney(c.totals.total_price) }}</div></div>
      <div class="card"><div class="label">已开票</div><div class="value">{{ fmtMoney(c.totals.billed) }}</div>
        <div class="sub">未开票 {{ fmtMoney(c.totals.unbilled) }}</div></div>
      <div class="card"><div class="label">已收款</div><div class="value">{{ fmtMoney(c.totals.received) }}</div></div>
      <div class="card"><div class="label">已确认收入</div><div class="value" style="color:var(--green)">{{ fmtMoney(c.totals.recognized) }}</div>
        <div class="sub">未来计划 {{ fmtMoney(c.totals.planned) }}</div></div>
      <div class="card"><div class="label">递延余额</div><div class="value" style="color:var(--blue)">{{ fmtMoney(c.totals.deferred) }}</div></div>
      <div class="card"><div class="label">待确认</div><div class="value" style="color:var(--amber)">{{ fmtMoney(c.totals.pending) }}</div></div>
    </div>

    <!-- 合同组成 -->
    <div class="panel">
      <h3 style="margin-top:0">合同组成（履约义务与独立售价）</h3>
      <table>
        <thead>
          <tr><th>履约义务</th><th>类型</th><th class="num">独立售价(SSP)</th><th>服务期/总量</th><th>验收证据</th></tr>
        </thead>
        <tbody>
          <tr v-for="ob in c.obligations" :key="ob.id">
            <td>{{ ob.name }}</td>
            <td><span class="badge gray">{{ ob.kind_label }}</span></td>
            <td class="num">{{ fmtMoney(ob.ssp) }}</td>
            <td>
              <span v-if="ob.kind === 'SUBSCRIPTION'">{{ ob.service_start }} ~ {{ ob.service_end }}</span>
              <span v-else-if="ob.kind === 'USAGE'">预计 {{ fmtMoney(ob.estimated_units) }}{{ ob.unit_label }}</span>
              <span v-else>一次性</span>
            </td>
            <td>
              <span v-if="ob.evidence" class="badge green">已验收 {{ ob.evidence.accepted_date }}（{{ ob.evidence.reference }}）</span>
              <span v-else-if="ob.kind === 'IMPLEMENTATION'" class="badge amber">缺证据 · 待确认</span>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 交易价格分摊 -->
    <div class="panel" v-if="c.current_allocation">
      <div class="section-head">
        <h3 style="margin:0">交易价格分摊（当前版本 v{{ c.current_allocation.version_no }}）</h3>
        <span class="formula">按 SSP 占比分摊；尾差 {{ fmtMoney(c.current_allocation.residual_amount) }} 稳定归属 SSP 最高义务</span>
      </div>
      <table>
        <thead>
          <tr><th>履约义务</th><th class="num">SSP快照</th><th class="num">分摊比例</th><th class="num">分摊金额</th><th>尾差归属</th></tr>
        </thead>
        <tbody>
          <tr v-for="l in c.current_allocation.lines" :key="l.id">
            <td>{{ l.obligation_name }}</td>
            <td class="num">{{ fmtMoney(l.ssp) }}</td>
            <td class="num">{{ fmtPct(l.ratio) }}</td>
            <td class="num"><strong>{{ fmtMoney(l.allocated_amount) }}</strong></td>
            <td><span v-if="l.is_residual_receiver" class="badge blue">尾差 {{ fmtMoney(c.current_allocation.residual_amount) }}</span></td>
          </tr>
          <tr class="total">
            <td>合计</td>
            <td class="num">{{ fmtMoney(c.current_allocation.total_ssp) }}</td>
            <td class="num">100%</td>
            <td class="num">{{ fmtMoney(c.current_allocation.total_price) }}</td>
            <td></td>
          </tr>
        </tbody>
      </table>
      <p class="muted">版本历史：
        <span v-for="v in c.allocation_versions" :key="v.id" style="margin-right:12px">
          v{{ v.version_no }}（{{ v.reason }}，{{ v.created_at.slice(0, 10) }}）
        </span>
      </p>
      <form class="inline" @submit.prevent="doReallocate">
        <label>重新分摊</label>
        <input v-model="reallocateReason" placeholder="变更原因" style="width:220px" />
        <button class="primary" :disabled="!reallocateReason">生成新版本</button>
      </form>
    </div>

    <!-- 确认计划 -->
    <div class="panel">
      <div class="section-head">
        <h3 style="margin:0">收入确认计划（按履约归属期间，非按开票）</h3>
        <span class="formula">每行均可追溯：确认行 → 分配行 → 分配版本</span>
      </div>
      <table>
        <thead>
          <tr><th>期间</th><th>履约义务</th><th class="num">金额</th><th>状态</th><th>来源</th><th>分配版本</th><th>备注</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in c.entries" :key="e.id">
            <td>{{ e.period || "—" }}</td>
            <td>{{ e.obligation_name }}</td>
            <td class="num">{{ fmtMoney(e.amount) }}</td>
            <td><span :class="STATUS_CLASS[e.status]">{{ e.status_label }}</span></td>
            <td>{{ e.source_label }}</td>
            <td>v{{ e.allocation_version_no }}</td>
            <td class="muted">{{ e.note }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 递延余额对照 -->
    <div class="panel">
      <div class="section-head">
        <h3 style="margin:0">递延余额逐期对照</h3>
        <span class="formula">期末递延 = 期初 + 当期开票 − 当期确认（收款为现金口径，单列）</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>期间</th><th>状态</th><th class="num">期初递延</th><th class="num">开票</th>
            <th class="num">收款</th><th class="num">确认收入</th><th class="num">期末递延</th><th class="num">未来计划</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in c.reconciliation" :key="r.period">
            <td>{{ r.period }}</td>
            <td><span :class="r.is_closed ? 'badge gray' : 'badge green'">{{ r.is_closed ? "已关闭" : "打开" }}</span></td>
            <td class="num">{{ fmtMoney(r.opening) }}</td>
            <td class="num">{{ fmtMoney(r.billed) }}</td>
            <td class="num">{{ fmtMoney(r.received) }}</td>
            <td class="num">{{ fmtMoney(r.recognized) }}</td>
            <td class="num"><strong>{{ fmtMoney(r.closing) }}</strong></td>
            <td class="num muted">{{ fmtMoney(r.planned) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 业务操作 -->
    <div class="panel">
      <h3 style="margin-top:0">业务登记（关闭期间将被拒绝）</h3>

      <template v-if="pendingImpls.length">
        <h3>登记验收证据</h3>
        <form class="inline" @submit.prevent="doEvidence">
          <select v-model="evidenceForm.obligation">
            <option v-for="ob in pendingImpls" :key="ob.id" :value="ob.id">{{ ob.name }}</option>
          </select>
          <input type="date" v-model="evidenceForm.accepted_date" />
          <input v-model="evidenceForm.title" placeholder="证据名称" />
          <input v-model="evidenceForm.reference" placeholder="验收单号" />
          <button class="primary">登记并确认</button>
        </form>
      </template>

      <template v-if="usageObligations.length">
        <h3>登记用量</h3>
        <form class="inline" @submit.prevent="doUsage">
          <select v-model="usageForm.obligation">
            <option v-for="ob in usageObligations" :key="ob.id" :value="ob.id">{{ ob.name }}</option>
          </select>
          <select v-model="usageForm.period">
            <option v-for="p in openPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
          <input v-model="usageForm.quantity" placeholder="数量" style="width:110px" />
          <button class="primary">登记</button>
        </form>
      </template>

      <h3>登记开票 / 收款</h3>
      <form class="inline" @submit.prevent="doInvoice">
        <label>开票</label>
        <input v-model="invoiceForm.number" placeholder="发票号" style="width:120px" />
        <input type="date" v-model="invoiceForm.invoice_date" />
        <input v-model="invoiceForm.amount" placeholder="金额" style="width:110px" />
        <select v-model="invoiceForm.period">
          <option v-for="p in openPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <button class="primary">登记开票</button>
      </form>
      <form class="inline" @submit.prevent="doPayment">
        <label>收款</label>
        <input type="date" v-model="paymentForm.received_date" />
        <input v-model="paymentForm.amount" placeholder="金额" style="width:110px" />
        <select v-model="paymentForm.period">
          <option v-for="p in openPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <button class="primary">登记收款</button>
      </form>

      <div v-if="message" :class="`alert ${messageType}`">{{ message }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import { fmtMoney, fmtPct, STATUS_CLASS } from "../format";

const route = useRoute();
const c = ref(null);
const periods = ref([]);
const message = ref("");
const messageType = ref("ok");

const reallocateReason = ref("");
const evidenceForm = ref({ obligation: null, accepted_date: "", title: "", reference: "" });
const usageForm = ref({ obligation: null, period: null, quantity: "" });
const invoiceForm = ref({ number: "", invoice_date: "", amount: "", period: null });
const paymentForm = ref({ received_date: "", amount: "", period: null });

const openPeriods = computed(() => periods.value.filter((p) => !p.is_closed));
const pendingImpls = computed(
  () => c.value?.obligations.filter((o) => o.kind === "IMPLEMENTATION" && !o.evidence) ?? []
);
const usageObligations = computed(
  () => c.value?.obligations.filter((o) => o.kind === "USAGE") ?? []
);

async function reload() {
  c.value = await api.contract(route.params.id);
}

async function run(action, success) {
  message.value = "";
  try {
    await action();
    messageType.value = "ok";
    message.value = success;
    await reload();
  } catch (err) {
    messageType.value = "error";
    message.value = err.message;
  }
}

const doReallocate = () =>
  run(() => api.reallocate(c.value.id, reallocateReason.value), "已生成新的分配版本");
const doEvidence = () =>
  run(
    () => api.addEvidence({ ...evidenceForm.value, note: "" }),
    "证据已登记，对应金额已在验收期间确认"
  );
const doUsage = () =>
  run(() => api.addUsage({ ...usageForm.value, note: "" }), "用量已登记并确认");
const doInvoice = () =>
  run(
    () => api.addInvoice({ ...invoiceForm.value, contract: c.value.id }),
    "发票已登记（不影响确认）"
  );
const doPayment = () =>
  run(
    () => api.addPayment({ ...paymentForm.value, contract: c.value.id }),
    "收款已登记（不影响确认）"
  );

onMounted(async () => {
  [periods.value] = await Promise.all([api.periods()]);
  await reload();
  if (pendingImpls.value.length) evidenceForm.value.obligation = pendingImpls.value[0].id;
  if (usageObligations.value.length) usageForm.value.obligation = usageObligations.value[0].id;
});
</script>
