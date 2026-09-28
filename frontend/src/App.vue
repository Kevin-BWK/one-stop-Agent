<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'

onLaunch(() => {
  // 应用启动（App 成品端 / H5 调试端共用）
})
</script>

<style>
/* uni-app H5：页面根容器要有确定高度，页面内才能用百分比铺满一屏 */
uni-page-body {
  height: 100%;
}

page {
  background-color: #f5f7fb;
  color: #1f2329;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Microsoft YaHei', sans-serif;
}
</style>