<template>
  <div>
    <header class="topbar">
      <div class="brand" @click="$router.push('/')">收入确认核算</div>
      <nav>
        <RouterLink to="/">总览</RouterLink>
        <RouterLink to="/periods">会计期间</RouterLink>
      </nav>
      <div class="policy-tag" title="示例政策仅用于本项目，不宣称覆盖所有会计准则">
        示例政策 · 仅限本项目
      </div>
    </header>
    <main class="container">
      <RouterView />
    </main>
  </div>
</template>
