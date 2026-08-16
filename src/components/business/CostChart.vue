<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { CostStat } from '@/types'

/** 成本/调用量趋势（docs/02 §6.2 / docs/03 §5.8）：ECharts 按需注册 */
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ data: CostStat | null }>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chart || !props.data) return
  const series = props.data.series ?? []
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['成本 (¥)', '调用量'] },
    grid: { left: 48, right: 48, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: series.map((s) => s.date) },
    yAxis: [
      { type: 'value', name: '成本' },
      { type: 'value', name: '调用量' },
    ],
    series: [
      { name: '成本 (¥)', type: 'line', smooth: true, data: series.map((s) => s.cost), itemStyle: { color: '#6366f1' } },
      { name: '调用量', type: 'bar', yAxisIndex: 1, data: series.map((s) => s.calls), itemStyle: { color: '#c1c2f9' }, barMaxWidth: 20 },
    ],
  })
}

watch(() => props.data, render, { deep: true })

onMounted(() => {
  if (el.value) chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', onResize)
})

function onResize() {
  chart?.resize()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="cost-chart" />
</template>

<style scoped>
.cost-chart {
  width: 100%;
  height: 300px;
}
</style>
