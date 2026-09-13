import { createRouter, createWebHistory } from "vue-router";
import DashboardView from "./views/DashboardView.vue";
import ContractDetailView from "./views/ContractDetailView.vue";
import PeriodsView from "./views/PeriodsView.vue";

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView },
    { path: "/contracts/:id", name: "contract", component: ContractDetailView },
    { path: "/periods", name: "periods", component: PeriodsView },
  ],
});
