import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: { lab: 'lab_rsa' } }) }))
vi.mock('../api', () => ({
  listLabs: vi.fn(async () => [{
    lab_definition_id: 'lab_rsa', course_id: 'course_data_security', code: 'EXP-RSA-001', name: 'RSA 非对称加密算法实验', category: '密码学', objective: '目标',
    latest_version: {
      lab_version_id: 'labv_rsa_v1', lab_definition_id: 'lab_rsa', version: 1, status: 'PUBLISHED', validation_errors: [], published_at: '2026-09-21T00:00:00',
      spec: {
        lab_definition_id: 'lab_rsa', version: 1, name: 'RSA 非对称加密算法实验', duration_minutes: 60, total_score: 100,
        nodes: [
          { node_key: 'student-rsa', display_name: '学生操作机', role: 'STUDENT', network_env: 'ISOLATED', network_keys: ['lab-net-rsa'], device_model: 'Ubuntu', image_id: 'img_ubuntu', image_digest: `sha256:${'1'.repeat(64)}`, cpu_limit: 1, memory_mb: 1024, ip_policy: 'AUTO', ports: [22], startup_command: '', mounts: [], position_x: 80, position_y: 80 },
          { node_key: 'target-rsa', display_name: '目标验证机', role: 'TARGET', network_env: 'ISOLATED', network_keys: ['lab-net-rsa'], device_model: 'Ubuntu', image_id: 'img_ubuntu', image_digest: `sha256:${'1'.repeat(64)}`, cpu_limit: 1, memory_mb: 1024, ip_policy: 'AUTO', ports: [22], startup_command: '', mounts: [], position_x: 360, position_y: 80 },
        ],
        networks: [{ network_key: 'lab-net-rsa', cidr_policy: 'AUTO_PRIVATE_24', internet_access: false, egress_allowlist: [], student_isolation: true }],
        image_bindings: [{ node_key: 'student-rsa', infra_image_id: 'img_ubuntu', digest: `sha256:${'1'.repeat(64)}` }, { node_key: 'target-rsa', infra_image_id: 'img_ubuntu', digest: `sha256:${'1'.repeat(64)}` }],
        steps: ['启动环境', '生成密钥', '公钥加密', '私钥解密', '签名验签', '提交报告'].map((name, index) => ({ node_key: `step-${index}`, name, description: name, order_no: index })),
        edges: [],
        checkpoints: [20, 20, 30, 20, 10].map((score, index) => ({ checkpoint_id: `cp-${index}`, dag_node_id: `step-${index + 1}`, name: `得分点 ${index + 1}`, score, judge_type: 'FILE_EXISTS', judge_target: 'file', judge_config_json: { path: 'file' }, failure_message: '失败', timeout_seconds: 10, order_no: index })),
        runtime_policy: { max_attempts: 3, timeout_minutes: 60 },
      },
    },
  }]),
  cloneVersion: vi.fn(), saveVersion: vi.fn(), validateVersion: vi.fn(), publishVersion: vi.fn(), exportVersion: vi.fn(), createRelease: vi.fn(), preflightRelease: vi.fn(), teacherPreview: vi.fn(),
}))

import LabBuilderView from './LabBuilderView.vue'

describe('实验设计器', () => {
  it('从接口数据展示 RSA 拓扑、DAG 和 100 分得分点', async () => {
    const wrapper = mount(LabBuilderView)
    await flushPromises()
    expect(wrapper.text()).toContain('RSA 非对称加密算法实验')
    const topology = wrapper.findAll('button').find(button => button.text().includes('场景拓扑'))
    await topology!.trigger('click')
    expect(wrapper.text()).toContain('student-rsa')
    expect(wrapper.text()).toContain('target-rsa')
    const dag = wrapper.findAll('button').find(button => button.text().includes('DAG 与判分'))
    await dag!.trigger('click')
    expect(wrapper.text()).toContain('5 个得分点')
    expect(wrapper.text()).toContain('100 / 100')
    expect(wrapper.findAll('tbody tr')).toHaveLength(5)
  })
})

