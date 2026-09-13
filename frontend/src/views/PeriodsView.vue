<template>
  <div>
    <h2>会计期间</h2>
    <p class="muted">关闭期间后，其中的确认、开票、收款、证据与用量记录均不能直接编辑；关闭动作会把该期间内的计划确认转为已确认。</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>期间</th><th>状态</th><th>关闭时间</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="p in periods" :key="p.id">
            <td>{{ p.label }}</td>
            <td><span :class="p.is_closed ? 'badge gray' : 'badge green'">{{ p.is_closed ? "已关闭" : "打开" }}</span></td>
            <td class="muted">{{ p.closed_at ? p.closed_at.slice(0, 19).replace("T", " ") : "—" }}</td>
            <td>
              <button v-if="!p.is_closed" class="danger" @click="close(p)">关闭期间</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="message" :class="`alert ${messageType}`">{{ message }}</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api";

const periods = ref([]);
const message = ref("");
const messageType = ref("ok");

async function reload() {
  periods.value = await api.periods();
}

async function close(p) {
  message.value = "";
  try {
    await api.closePeriod(p.id);
    messageType.value = "ok";
    message.value = `期间 ${p.label} 已关闭`;
    await reload();
  } catch (err) {
    messageType.value = "error";
    message.value = err.message;
  }
}

onMounted(reload);
</script>
