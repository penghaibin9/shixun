[CmdletBinding()]
param(
  [string]$OutputDir,
  [string]$WorkDir,
  [string]$OnlyLessonId,
  [ValidateSet('THEORY', 'LAB')]
  [string]$OnlyKind,
  [switch]$AllowPartial,
  [switch]$KeepWorkFiles
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$policyPath = Join-Path $repoRoot 'backend/app/resources/content/course-videos-v1.json'
$theoryPath = Join-Path $repoRoot 'backend/app/resources/content/theory-ppts-v1.json'
$labPath = Join-Path $repoRoot 'backend/app/resources/content/lab-packs-v1.json'
$questionPath = Join-Path $repoRoot 'backend/app/resources/content/question-bank-v1.json'
$pptDir = Join-Path $repoRoot 'outputs/01a0c33f-d483-7ac0-aa95-632194b582d5/theory-ppts-v1'
if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot 'outputs/01a0c33f-d483-7ac0-aa95-632194b582d5/course-videos-v1' }
if (-not $WorkDir) { $WorkDir = Join-Path $repoRoot 'backend/var/course-video-build-v1' }
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$WorkDir = [IO.Path]::GetFullPath($WorkDir)

function Find-MediaTool([string]$Name) {
  $override = if ($Name -eq 'ffmpeg') { $env:YUEKE_FFMPEG } else { $env:YUEKE_FFPROBE }
  if ($override -and (Test-Path -LiteralPath $override -PathType Leaf)) { return [IO.Path]::GetFullPath($override) }
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft/WinGet/Packages'
  $candidate = Get-ChildItem -LiteralPath $packageRoot -Recurse -Filter "$Name.exe" -ErrorAction SilentlyContinue |
    Where-Object FullName -Match 'Gyan\.FFmpeg_' |
    Sort-Object FullName -Descending |
    Select-Object -First 1
  if ($candidate) { return $candidate.FullName }
  throw "未找到 $Name。请先安装 Gyan.FFmpeg，或设置 YUEKE_$($Name.ToUpper())。"
}

function Get-CurriculumAuthority {
  $python = @(
    (Join-Path $repoRoot '.venv/Scripts/python.exe'),
    (Join-Path $repoRoot 'backend/.venv/Scripts/python.exe')
  ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
  if (-not $python) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw '未找到 Python，无法读取 A 线权威课程目录' }
    $python = $pythonCommand.Source
  }

  $previousPythonPath = $env:PYTHONPATH
  $previousPythonUtf8 = $env:PYTHONUTF8
  try {
    $env:PYTHONPATH = Join-Path $repoRoot 'backend'
    $env:PYTHONUTF8 = '1'
    $authorityJson = (& $python -c "import json; from app.teaching.catalog import curriculum_rows; print(json.dumps(curriculum_rows('$($policy.courseId)'), ensure_ascii=False))") -join "`n"
    if ($LASTEXITCODE -ne 0) { throw '读取 A 线权威课程目录失败' }
    return $authorityJson | ConvertFrom-Json
  } finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
  }
}

function Escape-ConcatPath([string]$Path) {
  return ([IO.Path]::GetFullPath($Path).Replace('\', '/').Replace("'", "'\''"))
}

function Format-SrtTime([double]$Seconds) {
  $span = [TimeSpan]::FromSeconds([Math]::Max(0, $Seconds))
  return '{0:00}:{1:00}:{2:00},{3:000}' -f [Math]::Floor($span.TotalHours), $span.Minutes, $span.Seconds, $span.Milliseconds
}

function Normalize-SpeechText([string]$Text) {
  $result = $Text
  $terms = [ordered]@{
    'SHA-256' = 'S H A 二五六'; 'SHA' = 'S H A'; 'AES' = 'A E S'; 'DES' = 'D E S';
    'RSA' = 'R S A'; 'MD5' = 'M D 五'; 'SM2' = 'S M 二'; 'SM3' = 'S M 三'; 'SM4' = 'S M 四';
    'Base64' = 'Base 六四'; 'RBAC' = 'R B A C'; 'ECB' = 'E C B'; 'CBC' = 'C B C';
    'TLS' = 'T L S'; 'HTTPS' = 'H T T P S'; 'IoT' = 'I O T'; 'MFA' = 'M F A';
    'MPC' = 'M P C'; 'PoC' = 'P O C'; 'RPO' = 'R P O'; 'RTO' = 'R T O';
    'UTF-8' = 'U T F 八'; 'IETF' = 'I E T F'; 'RFC' = 'R F C'; 'NIST' = 'N I S T';
    'FIPS' = 'F I P S'; 'SQL' = 'S Q L'; 'LSB' = 'L S B'; 'PPM' = 'P P M';
    'Python' = '派森'; 'Linux' = '里纳克斯'; 'OpenSSL' = 'Open S S L'; 'MySQL' = 'My S Q L'
  }
  foreach ($entry in $terms.GetEnumerator()) {
    $result = $result.Replace($entry.Key, $entry.Value)
  }
  return $result
}

function New-PointNarration([string]$CourseTitle, [string]$ConceptTitle, [string]$Point, [int]$PointNo) {
  switch ($PointNo) {
    1 { return "第一个观察点是：$Point。先确定这句话约束的对象，把对象写入资产清单或数据流，再标出谁负责、从哪里进入、允许执行哪些动作。在《${ConceptTitle}》中，对象不清会让后续授权和审计失去落点。落地时应记录责任人、触发条件和检查结果，并用一条正向测试与一条拒绝测试确认边界。最后问自己：如果对象换成另一类数据，这条规则是否仍成立，依据是什么。" }
    2 { return "第二个观察点是：$Point。这一条重点检查业务边界。分析时分别列出允许情形、禁止情形和需要重新审批的变化情形，不能用一个笼统开关覆盖所有使用者。围绕《${ConceptTitle}》，应把目的、范围、角色和期限写成可执行条件。验证时选择一个边界内样例和一个越界样例，确认前者得到预期结果、后者被拒绝并留下日志。" }
    3 { return "第三个观察点是：$Point。这里要从原则进入实施。把这句话转换成四项动作：准备可信输入，执行明确控制，保存结构化结果，安排责任人复核。实施记录至少包含时间、对象、操作者、结果和异常说明。若只能看到成功截图，却找不到输入、返回码或审计事件，就还不能证明《${ConceptTitle}》已经有效落地。" }
    4 { return "第四个观察点是：$Point。可以用反例检验理解：假设新增数据来源、外部合作方或系统迁移，原有判断是否还成立？如果不确定，就重新核对数据流、授权关系、保留期限和退出处置。把变化前后的证据并列比较，才能发现控制是否被绕过。这个观察点也提醒我们，安全结论有适用条件，需要定期复核而不是一次配置后永久有效。" }
    default { return "补充观察点是：$Point。请把它与前四项放在同一条控制链中，说明前置条件、执行动作、输出证据和失败处置。再选择一个新业务场景复述这条规则，确认它不是只对课件中的例子成立。" }
  }
}

function New-TheorySections($Lesson, $Question) {
  $sections = [Collections.Generic.List[object]]::new()
  $sections.Add([pscustomobject]@{
    title = '课程导入'
    text = @"
大家好，本课学习“$($Lesson.title)”。这一课不是让大家孤立记忆术语，而是建立能够用于分析、设计和复核的工作方法。学习过程中请始终保留三个问题：我们保护的对象是什么，风险通过哪条路径发生，最终用什么证据证明控制有效。
先看课程位置。本课编号是 $($Lesson.lessonCode)，属于《数据安全技术基础》的连续知识链。前置知识帮助我们识别数据、主体和处理活动，本课负责把这些事实转成可以执行的安全判断，后续课时还会把判断落到技术配置、实验验证和审计记录。
建议准备一张纸，分成“事实、风险、控制、证据”四栏。听到概念时先记事实，听到案例时标出风险，听到方法时写下控制，最后补充可以检查的证据。这样学完以后得到的不是一串定义，而是一份可以复用的分析框架。
本视频内容来自正式课程课件、题库和列明的参考资料。讲解会先说明目标，再逐个展开核心概念，然后用业务案例串联，最后通过知识检查完成回顾。现在开始本课。
"@
  })
  $objectiveText = ($Lesson.learningObjectives | ForEach-Object { "学习目标：$_" }) -join "`n"
  $structureText = ($Lesson.conceptSlides | ForEach-Object -Begin { $i = 0 } -Process { $i++; "第 $i 部分是 $($_.title)。" }) -join "`n"
  $sections.Add([pscustomobject]@{
    title = '学习目标与知识结构'
    text = @"
先明确学习结果。$objectiveText
这两个目标分别回答“能不能识别”和“能不能行动”。识别要求我们说清对象、参与者、边界和风险，行动要求我们能提出控制、说明理由，并给出验证方式。只会复述定义还不够，只有能够在新场景中完成判断，才算达到目标。
本课的知识结构如下。$structureText
学习时不要把这些部分割裂开。每个概念都要回答四个问题：它解决什么问题，它依赖哪些前提，它可能被怎样误用，以及怎样留下可核验的结果。遇到陌生术语，可以先用普通业务语言复述，再回到专业名称，这能显著减少机械记忆。
下面给出本课的自检标准。第一，能用自己的话解释各概念之间的关系。第二，面对案例时能定位至少一个风险路径。第三，提出的控制包含责任、条件和证据。第四，能够说明方案的适用边界。带着这四条标准进入后续内容。
"@
  })
  $conceptNo = 0
  foreach ($concept in $Lesson.conceptSlides) {
    $conceptNo++
    $pointNarration = [Collections.Generic.List[string]]::new()
    $pointNo = 0
    foreach ($point in $concept.points) {
      $pointNo++
      $pointNarration.Add((New-PointNarration -CourseTitle $Lesson.title -ConceptTitle $concept.title -Point $point -PointNo $pointNo))
    }
    $sections.Add([pscustomobject]@{
      title = $concept.title
      text = @"
现在进入第 $conceptNo 个核心概念：$($concept.title)。$($concept.explanation)
理解这一部分时，先区分“概念成立的条件”和“控制落地的动作”。条件用于判断是否适用，动作用于指导系统、流程和人员。两者混在一起，容易出现规则写得很完整、实际却无法执行的问题。
$($pointNarration -join "`n")
回顾这一部分：$($concept.title) 不是孤立的产品功能，而是一组有输入、有判断、有输出的控制活动。请暂停几秒，尝试用一句话说明它保护什么，再写出一项可以检查的证据。如果无法写出证据，就重新检查刚才的对象、动作和边界是否足够具体。
"@
    })
  }
  $sections.Add([pscustomobject]@{
    title = '业务案例'
    text = @"
下面把概念放回业务案例。$($Lesson.caseExample)
分析案例时先只记录事实，不急着给结论。列出出现的数据、系统、人员、合作方和时间节点，再画出数据从哪里来、经过哪里、最终到哪里去。事实和推测要分开，缺失的信息要明确标注，不能用经验直接补齐。
第二步识别风险路径。可以从未授权获知、错误修改、无法使用、超范围处理和责任无法追溯几个角度检查。每个风险都要对应一个触发条件和一个可能后果。风险描述越具体，后续控制越容易验证。
第三步设计控制。优先处理影响大且发生条件明确的路径，并说明控制发生在事前、事中还是事后。事前包括审批和配置，事中包括身份鉴别、最小权限、加密或脱敏，事后包括日志、告警、复核和销毁证明。不要把购买工具当作控制完成，工具必须进入真实流程。
第四步验证。为每项控制选择证据，例如配置快照、测试记录、审批单、日志事件、摘要值或恢复报告。证据应能说明谁在什么时候对什么对象执行了什么动作，以及结果是否符合预期。
现在做一次迁移练习：如果案例中的数据规模扩大十倍，或者接收方从校内部门变成外部机构，哪些判断必须重新进行？请用本课的核心概念回答，并指出至少一项需要新增或加强的证据。
"@
  })
  $sections.Add([pscustomobject]@{
    title = '知识检查与总结'
      text = @"
进入知识检查。问题是：$($Lesson.knowledgeCheck.question)
请先暂停并独立组织答案。回答时至少包含判断依据、关键动作和验证证据，不要只写一个名词。
参考答案是：$($Lesson.knowledgeCheck.answer)
对照时关注逻辑，而不是逐字一致。一个完整答案应说明为什么这样判断、在哪个边界内成立，以及如何确认执行结果。如果自己的答案缺少其中一项，请补写后再继续。
再用正式题库完成四类检验。填空题：$($Question.fill[0])，答案是 $($Question.fill[1])。解析是：$($Question.fill[2])
单选题：$($Question.single[0])。四个选项依次是：$($Question.single[1] -join '；')。正确选项是 $($Question.single[2])。解析是：$($Question.single[3])
多选题：$($Question.multiple[0])。选项依次是：$($Question.multiple[1] -join '；')。正确选项是 $($Question.multiple[2] -join '、')。解析是：$($Question.multiple[3])
判断题：$($Question.trueFalse[0])。正确答案是 $($Question.trueFalse[1])。解析是：$($Question.trueFalse[2])
完成后不要只核对字母，要说出每个干扰项为什么不成立。这样才能发现自己是理解了边界，还是只记住了答案位置。
最后总结本课。我们从学习目标出发，依次讨论了 $((($Lesson.conceptSlides | ForEach-Object title) -join '、'))，并用业务案例把概念转成事实、风险、控制和证据。复习时建议重新绘制一遍四栏表，并从题库中分别完成填空、单选、多选和判断练习。
请记住三个带走的问题：保护对象是否清楚，控制边界是否明确，验证证据是否足够。能够稳定回答这三个问题，就能把本课知识迁移到新的系统和业务中。本课到这里结束。
"@
  })
  return $sections
}

function New-LabSections($Lesson, $Question) {
  $sections = [Collections.Generic.List[object]]::new()
  $principles = ($Lesson.principles | ForEach-Object { "原理要点：$_" }) -join "`n"
  $steps = ($Lesson.steps | ForEach-Object -Begin { $i = 0 } -Process { $i++; "第 $i 步，$_" }) -join "`n"
  $sections.Add([pscustomobject]@{
    title = '实验导入'
    text = @"
大家好，本次实验是“$($Lesson.title)”。实验目标是：$($Lesson.objective)
这不是只追求命令执行成功的操作演示。完整实验必须说明原理、保留输入、记录步骤、验证输出，并能解释失败现象。开始前请确认使用的是隔离教学环境，不要把示例密钥、账号、数据或攻击性操作带到真实生产系统。
本视频会按照准备、原理、步骤、验证和清理的顺序讲解。建议一边观看一边打开实验文件包，但先阅读说明再运行命令。每一步都要观察预期产物，并把终端输出或报告保存为可复核证据。
"@
  })
  $sections.Add([pscustomobject]@{
    title = '环境与原理'
    text = @"
实验环境是：$($Lesson.environment)
$principles
在动手前先建立安全边界。确认实验目录、输入文件和输出目录，检查工具版本，并准备失败后的清理方式。涉及密钥、权限、数据库或日志时，使用专用实验数据和最小权限账户。不要复用正式密码，也不要连接不在授权范围内的目标。
理解原理时要区分“现象”和“原因”。命令输出只说明发生了什么，原理解释为什么发生。后续验证必须同时包含正向路径和至少一个反向路径，例如正确输入成功、篡改输入失败，或授权角色允许、未授权角色拒绝。
"@
  })
  $sections.Add([pscustomobject]@{
    title = '步骤总览'
    text = @"
先看完整步骤。$steps
执行时每一步都采用同一记录格式：输入是什么，执行了什么，预期看到什么，实际结果是什么。若实际结果不同，先停止后续步骤，检查路径、版本、权限和输入格式，不要通过关闭校验或扩大权限来掩盖错误。
为了保证可重复，建议从干净目录开始，并在每一步后检查文件大小、摘要、返回码或结构化报告。能够在第二次运行得到一致结论，才说明实验流程真正稳定。
"@
  })
  $stepNo = 0
  foreach ($step in $Lesson.steps) {
    $stepNo++
    $sections.Add([pscustomobject]@{
      title = "步骤 $stepNo"
      text = @"
现在执行第 $stepNo 步：$step
开始前先确认输入来自本实验文件包，路径没有指向个人目录或真实业务数据。执行过程中关注命令返回码、标准输出和新生成的文件；如果工具要求密码或密钥，应通过实验变量或受控文件提供，不要写入日志和截图。
这一步的关键不是照抄命令，而是理解输入经过了什么转换。请尝试预测执行结果，再实际运行并比较。预测一致说明已理解基本路径；预测不一致时，记录差异并回到原理检查假设。
完成后做三项核对。第一，预期文件或状态确实出现。第二，结果内容能被独立工具或检查脚本验证。第三，异常输入不会被错误判定为成功。把核对结果写进实验报告，形成从操作到证据的闭环。
最后考虑可重复性：如果换一组教学数据，步骤是否仍然成立？如果依赖固定路径、固定时间或未说明的权限，应在报告中指出并修正。完成这些检查后再进入下一步。
"@
    })
  }
  $expected = ($Lesson.expected | ForEach-Object { "$_" }) -join '、'
  $sections.Add([pscustomobject]@{
    title = '验证、清理与提交'
    text = @"
所有步骤完成后，集中验证实验。预期产物包括：$expected。推荐验证命令是：$($Lesson.verifyCommand)。
运行验证前先保留原始输出，避免检查脚本覆盖证据。验证成功时记录工具版本、执行时间、返回码和关键摘要；验证失败时保留错误信息，不要只截取最后一行。错误本身也是定位环境或理解偏差的重要证据。
接着执行反向检查。修改一个输入、移除一项权限或破坏一个摘要，确认验证能够识别异常。只有正向成功而没有反向拒绝，不能充分证明控制有效。
最后清理临时密钥、测试账户、容器、网络和敏感中间文件，但保留课程要求的报告和无敏感信息的验证结果。提交前按“目标、环境、原理、步骤、结果、问题与改进”检查报告结构。
本实验到这里结束。请不要只提交一张成功截图，要提交能够让另一位同学复现并判断结果的证据链。
提交前再做四类题复核。填空题：$($Question.fill[0])，答案是 $($Question.fill[1])。单选题：$($Question.single[0])，正确选项是 $($Question.single[2])。多选题：$($Question.multiple[0])，正确选项是 $($Question.multiple[2] -join '、')。判断题：$($Question.trueFalse[0])，正确答案是 $($Question.trueFalse[1])。请结合实验现象说明理由，不要只记录答案字母。
"@
  })
  return $sections
}

function New-LabSlide([string]$Path, [string]$Code, [string]$Title, [string]$Body, [int]$Index, [int]$Total) {
  Add-Type -AssemblyName System.Drawing
  $bitmap = [Drawing.Bitmap]::new(1280, 720)
  $graphics = [Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.TextRenderingHint = [Drawing.Text.TextRenderingHint]::ClearTypeGridFit
  $graphics.Clear([Drawing.Color]::FromArgb(245, 247, 251))
  $navy = [Drawing.Color]::FromArgb(16, 33, 63)
  $blue = [Drawing.Color]::FromArgb(36, 87, 245)
  $text = [Drawing.Color]::FromArgb(23, 32, 51)
  $muted = [Drawing.Color]::FromArgb(102, 112, 133)
  $white = [Drawing.Color]::White
  $graphics.FillRectangle([Drawing.SolidBrush]::new($navy), 0, 0, 1280, 104)
  $graphics.FillRectangle([Drawing.SolidBrush]::new($blue), 0, 104, 18, 616)
  $titleFont = [Drawing.Font]::new('Microsoft YaHei', 28, [Drawing.FontStyle]::Bold)
  $codeFont = [Drawing.Font]::new('Microsoft YaHei', 17, [Drawing.FontStyle]::Bold)
  $bodyFont = [Drawing.Font]::new('Microsoft YaHei', 22, [Drawing.FontStyle]::Regular)
  $footerFont = [Drawing.Font]::new('Microsoft YaHei', 12, [Drawing.FontStyle]::Regular)
  $graphics.DrawString($Code, $codeFont, [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(220, 231, 255)), 58, 35)
  $graphics.DrawString($Title, $titleFont, [Drawing.SolidBrush]::new($white), [Drawing.RectangleF]::new(220, 24, 980, 62))
  $format = [Drawing.StringFormat]::new()
  $format.Trimming = [Drawing.StringTrimming]::EllipsisWord
  $graphics.DrawString($Body, $bodyFont, [Drawing.SolidBrush]::new($text), [Drawing.RectangleF]::new(78, 154, 1120, 460), $format)
  $graphics.DrawString('数据安全技术基础 · 实验讲解', $footerFont, [Drawing.SolidBrush]::new($muted), 78, 672)
  $graphics.DrawString(("{0:00} / {1:00}" -f $Index, $Total), $footerFont, [Drawing.SolidBrush]::new($muted), 1110, 672)
  $bitmap.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
  $format.Dispose(); $footerFont.Dispose(); $bodyFont.Dispose(); $codeFont.Dispose(); $titleFont.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
}

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
  & $Program @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Program 执行失败，退出码 $LASTEXITCODE" }
}

$ffmpeg = Find-MediaTool 'ffmpeg'
$ffprobe = Find-MediaTool 'ffprobe'
$policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json
$theory = Get-Content -LiteralPath $theoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$labs = Get-Content -LiteralPath $labPath -Raw -Encoding UTF8 | ConvertFrom-Json
$questions = Get-Content -LiteralPath $questionPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($policy.courseId -ne $theory.courseId -or $policy.courseId -ne $labs.courseId -or $policy.courseId -ne $questions.courseId) { throw '视频、课件、实验和题库内容源的课程标识不一致' }
if ($theory.lessons.Count -ne 37 -or $labs.packs.Count -ne 12) { throw '正式内容源必须包含 37 个理论课时和 12 个实验课时' }
$authority = Get-CurriculumAuthority
$authorityByLesson = @{}
foreach ($authorityLesson in $authority.lessons) { $authorityByLesson[$authorityLesson.lesson_id] = $authorityLesson }
if ($authorityByLesson.Count -ne 49) { throw 'A 线权威课程目录必须包含 49 个课时' }
$sourceLessons = @($theory.lessons) + @($labs.packs)
foreach ($lesson in $sourceLessons) {
  $authorityLesson = $authorityByLesson[$lesson.lessonId]
  if (-not $authorityLesson) { throw "A 线权威课程目录缺少课时：$($lesson.lessonId)" }
  if ($authorityLesson.lesson_code -ne $lesson.lessonCode) { throw "课时编号不一致：$($lesson.lessonId)" }
  $lesson.title = $authorityLesson.title
}
$questionByLesson = @{}
foreach ($questionLesson in $questions.lessons) { $questionByLesson[$questionLesson.lessonId] = $questionLesson }
if ($questionByLesson.Count -ne 49) { throw '正式题库必须覆盖 49 个课时' }

$jobs = [Collections.Generic.List[object]]::new()
foreach ($lesson in $theory.lessons) {
  $code = ($lesson.lessonCode -split '\.' | ForEach-Object { $_.PadLeft(2, '0') }) -join '-'
  $jobs.Add([pscustomobject]@{ kind = 'THEORY'; lesson = $lesson; filename = "theory-$code-v1.mp4"; ppt = Join-Path $pptDir "theory-$code-v1.pptx" })
}
foreach ($lesson in $labs.packs) {
  $number = ([regex]::Match($lesson.lessonCode, '\d+').Value).PadLeft(2, '0')
  $jobs.Add([pscustomobject]@{ kind = 'LAB'; lesson = $lesson; filename = "lab-$number-v1.mp4"; ppt = $null })
}
if ($OnlyLessonId) { $jobs = [Collections.Generic.List[object]]@($jobs | Where-Object { $_.lesson.lessonId -eq $OnlyLessonId }) }
if ($OnlyKind) { $jobs = [Collections.Generic.List[object]]@($jobs | Where-Object { $_.kind -eq $OnlyKind }) }
if ($jobs.Count -eq 0) { throw "未找到课时：$OnlyLessonId" }
if (-not $AllowPartial -and $jobs.Count -ne 49) { throw '部分生成必须显式使用 -AllowPartial' }

if (Test-Path -LiteralPath $OutputDir) {
  if ((Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) { throw "输出目录必须为空：$OutputDir" }
} else { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }
if (Test-Path -LiteralPath $WorkDir) {
  if ((Get-ChildItem -LiteralPath $WorkDir -Force).Count -gt 0) { throw "工作目录必须为空：$WorkDir" }
} else { New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null }

Add-Type -AssemblyName System.Speech
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$speaker.SelectVoice($policy.narration.voice)
$speaker.Rate = [int]$policy.narration.labRate
$powerPoint = $null
$results = [Collections.Generic.List[object]]::new()
$culture = [Globalization.CultureInfo]::InvariantCulture

try {
  foreach ($job in $jobs) {
    $lesson = $job.lesson
    $narrationRate = if ($job.kind -eq 'THEORY' -and $lesson.conceptSlides.Count -ge $policy.narration.denseTheoryConceptThreshold) {
      [int]$policy.narration.denseTheoryRate
    } elseif ($job.kind -eq 'THEORY') {
      [int]$policy.narration.theoryRate
    } else {
      [int]$policy.narration.labRate
    }
    $speaker.Rate = $narrationRate
    $lessonWork = Join-Path $WorkDir $lesson.lessonId
    $imageDir = Join-Path $lessonWork 'slides'
    $audioDir = Join-Path $lessonWork 'audio'
    New-Item -ItemType Directory -Path $imageDir, $audioDir -Force | Out-Null
    $question = $questionByLesson[$lesson.lessonId]
    if (-not $question) { throw "$($lesson.lessonCode) 缺少四类题型" }
    $sections = if ($job.kind -eq 'THEORY') { New-TheorySections $lesson $question } else { New-LabSections $lesson $question }

    if ($job.kind -eq 'THEORY') {
      if (-not (Test-Path -LiteralPath $job.ppt -PathType Leaf)) { throw "理论课件不存在：$($job.ppt)" }
      if (-not $powerPoint) { $powerPoint = New-Object -ComObject PowerPoint.Application }
      $deck = $powerPoint.Presentations.Open($job.ppt, $true, $true, $false)
      try { $deck.Export($imageDir, 'PNG', 1280, 720) } finally { $deck.Close() }
      $images = @(Get-ChildItem -LiteralPath $imageDir -Filter '*.PNG' | Sort-Object { [int]([regex]::Match($_.BaseName, '\d+').Value) })
      if ($images.Count -ne $sections.Count) { throw "$($lesson.lessonCode) 课件页数与讲稿段数不一致：$($images.Count)/$($sections.Count)" }
    } else {
      $total = $sections.Count
      for ($i = 0; $i -lt $total; $i++) {
        $body = if ($i -eq 0) { $lesson.objective } elseif ($i -eq 1) { "$($lesson.environment)`n`n$($lesson.principles -join "`n")" } elseif ($i -eq 2) { $lesson.steps -join "`n" } elseif ($i -eq ($total - 1)) { "预期产物：`n$($lesson.expected -join "`n")`n`n验证命令：`n$($lesson.verifyCommand)" } else { "当前任务`n$($lesson.steps[$i - 3])`n`n执行检查`n• 使用隔离环境与实验数据`n• 先预测结果，再执行并比较`n• 记录返回码、产物和异常`n• 用检查脚本或反向样例复核" }
        $imagePath = Join-Path $imageDir ("slide-{0:00}.png" -f ($i + 1))
        New-LabSlide -Path $imagePath -Code $lesson.lessonCode -Title $sections[$i].title -Body $body -Index ($i + 1) -Total $total
      }
      $images = @(Get-ChildItem -LiteralPath $imageDir -Filter '*.png' | Sort-Object Name)
    }

    $durations = [Collections.Generic.List[double]]::new()
    $audioFiles = [Collections.Generic.List[string]]::new()
    $transcriptParts = [Collections.Generic.List[string]]::new()
    for ($i = 0; $i -lt $sections.Count; $i++) {
      $text = (([string]$sections[$i].text).Trim() -replace '。{2,}', '。')
      $transcriptParts.Add("【$($i + 1) · $($sections[$i].title)】`r`n$text")
      $wave = Join-Path $audioDir ("section-{0:00}.wav" -f ($i + 1))
      $speaker.SetOutputToWaveFile($wave)
      $speaker.Speak((Normalize-SpeechText $text))
      $speaker.SetOutputToNull()
      $probeDuration = & $ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 $wave
      if ($LASTEXITCODE -ne 0) { throw "音频时长解析失败：$wave" }
      $durations.Add([double]::Parse(($probeDuration | Select-Object -First 1), $culture))
      $audioFiles.Add($wave)
    }

    $duration = ($durations | Measure-Object -Sum).Sum
    if ($job.kind -eq 'THEORY' -and ($duration -lt $policy.durationPolicy.theoryMinimumSeconds -or $duration -gt $policy.durationPolicy.theoryMaximumSeconds)) {
      throw "$($lesson.lessonCode) 理论讲稿时长 $([Math]::Round($duration)) 秒，不在 35～45 分钟门禁内"
    }
    if ($job.kind -eq 'LAB' -and $duration -lt $policy.durationPolicy.labMinimumSeconds) {
      throw "$($lesson.lessonCode) 实验讲稿时长 $([Math]::Round($duration)) 秒，低于最低 10 分钟"
    }

    $baseName = [IO.Path]::GetFileNameWithoutExtension($job.filename)
    $transcriptPath = Join-Path $OutputDir "$baseName-transcript.txt"
    $captionPath = Join-Path $OutputDir "$baseName.srt"
    [IO.File]::WriteAllText($transcriptPath, (($transcriptParts -join "`n`n") + "`n"), [Text.UTF8Encoding]::new($false))

    $captionLines = [Collections.Generic.List[string]]::new()
    $captionIndex = 0
    $offset = 0.0
    for ($i = 0; $i -lt $sections.Count; $i++) {
      $sentences = @([regex]::Matches(([string]$sections[$i].text).Trim(), '[^。！？；]+[。！？；]?') | ForEach-Object { $_.Value.Trim() } | Where-Object { $_ })
      $weightTotal = ($sentences | ForEach-Object { [Math]::Max(1, $_.Length) } | Measure-Object -Sum).Sum
      $cursor = $offset
      foreach ($sentence in $sentences) {
        $captionIndex++
        $slice = $durations[$i] * ([Math]::Max(1, $sentence.Length) / $weightTotal)
        $end = [Math]::Min($offset + $durations[$i], $cursor + $slice)
        $captionLines.Add([string]$captionIndex)
        $captionLines.Add("$(Format-SrtTime $cursor) --> $(Format-SrtTime $end)")
        $captionLines.Add($sentence)
        $captionLines.Add('')
        $cursor = $end
      }
      $offset += $durations[$i]
    }
    if ($captionLines.Count -gt 0 -and $captionLines[$captionLines.Count - 1] -eq '') {
      $captionLines.RemoveAt($captionLines.Count - 1)
    }
    [IO.File]::WriteAllText($captionPath, (($captionLines -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))

    $audioConcat = Join-Path $lessonWork 'audio.ffconcat'
    $audioConcatLines = @('ffconcat version 1.0') + @($audioFiles | ForEach-Object { "file '$(Escape-ConcatPath $_)'" })
    [IO.File]::WriteAllLines($audioConcat, $audioConcatLines, [Text.UTF8Encoding]::new($false))
    $mergedWave = Join-Path $lessonWork 'narration.wav'
    Invoke-Checked $ffmpeg @('-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', $audioConcat, '-c:a', 'pcm_s16le', '-y', $mergedWave)

    $visualConcat = Join-Path $lessonWork 'visuals.ffconcat'
    $visualLines = [Collections.Generic.List[string]]::new()
    $visualLines.Add('ffconcat version 1.0')
    for ($i = 0; $i -lt $images.Count; $i++) {
      $visualLines.Add("file '$(Escape-ConcatPath $images[$i].FullName)'" )
      $visualLines.Add("duration $($durations[$i].ToString('0.000', $culture))")
    }
    $visualLines.Add("file '$(Escape-ConcatPath $images[-1].FullName)'" )
    [IO.File]::WriteAllLines($visualConcat, $visualLines, [Text.UTF8Encoding]::new($false))

    $videoPath = Join-Path $OutputDir $job.filename
    Invoke-Checked $ffmpeg @(
      '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', $visualConcat,
      '-i', $mergedWave, '-i', $captionPath,
      '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0',
      '-vf', 'fps=1,format=yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-crf', '32',
      '-c:a', 'aac', '-b:a', '64k', '-ar', '22050', '-ac', '1', '-c:s', 'mov_text',
      '-metadata:s:s:0', 'language=zho', '-movflags', '+faststart', '-shortest', '-y', $videoPath
    )

    $probeJson = (& $ffprobe -v error -show_entries 'format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height' -of json $videoPath) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "视频媒体解析失败：$videoPath" }
    $probe = $probeJson | ConvertFrom-Json
    $videoStream = $probe.streams | Where-Object codec_type -eq 'video' | Select-Object -First 1
    $audioStream = $probe.streams | Where-Object codec_type -eq 'audio' | Select-Object -First 1
    $subtitleStream = $probe.streams | Where-Object codec_type -eq 'subtitle' | Select-Object -First 1
    if (-not $videoStream -or -not $audioStream -or -not $subtitleStream) { throw "$($lesson.lessonCode) 缺少视频、音频或字幕流" }
    if ($videoStream.width -ne 1280 -or $videoStream.height -ne 720) { throw "$($lesson.lessonCode) 视频分辨率不符合 1280×720" }
    $actualDuration = [int][Math]::Round([double]::Parse([string]$probe.format.duration, $culture))
    if ([Math]::Abs($actualDuration - [int][Math]::Round($duration)) -gt 2) { throw "$($lesson.lessonCode) 合成时长与旁白时长不一致" }
    $results.Add([ordered]@{
      lesson_id = $lesson.lessonId
      lesson_code = $lesson.lessonCode
      lesson_kind = $job.kind
      title = $lesson.title
      filename = $job.filename
      transcript_filename = [IO.Path]::GetFileName($transcriptPath)
      caption_filename = [IO.Path]::GetFileName($captionPath)
      duration_seconds = $actualDuration
      width = [int]$videoStream.width
      height = [int]$videoStream.height
      video_codec = $videoStream.codec_name
      audio_codec = $audioStream.codec_name
      subtitle_codec = $subtitleStream.codec_name
      size_bytes = (Get-Item -LiteralPath $videoPath).Length
      sha256 = (Get-FileHash -LiteralPath $videoPath -Algorithm SHA256).Hash.ToLowerInvariant()
      transcript_sha256 = (Get-FileHash -LiteralPath $transcriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
      caption_sha256 = (Get-FileHash -LiteralPath $captionPath -Algorithm SHA256).Hash.ToLowerInvariant()
      narration_voice = $policy.narration.voice
      narration_rate = $narrationRate
      automated_media_check = 'PASS'
      human_sampling = 'PENDING'
    })
    Write-Host "$($lesson.lessonCode) $($job.kind) $actualDuration 秒 $([Math]::Round((Get-Item $videoPath).Length / 1MB, 2)) MB"
    if (-not $KeepWorkFiles) { Remove-Item -LiteralPath $lessonWork -Recurse -Force }
  }
} finally {
  $speaker.Dispose()
  if ($powerPoint) { $powerPoint.Quit(); [Runtime.InteropServices.Marshal]::FinalReleaseComObject($powerPoint) | Out-Null }
}

$index = [ordered]@{
  schema_version = '1.0'
  content_version = $policy.version
  course_id = $policy.courseId
  generated_at = [DateTime]::UtcNow.ToString('o')
  complete = ($results.Count -eq 49)
  video_count = $results.Count
  theory_count = @($results | Where-Object lesson_kind -eq 'THEORY').Count
  lab_count = @($results | Where-Object lesson_kind -eq 'LAB').Count
  duration_total_seconds = ($results | ForEach-Object { [int]$_['duration_seconds'] } | Measure-Object -Sum).Sum
  duration_policy = $policy.durationPolicy
  technical_profile = $policy.video
  review_policy = $policy.reviewPolicy
  videos = $results
}
[IO.File]::WriteAllText((Join-Path $OutputDir 'index.json'), (($index | ConvertTo-Json -Depth 12) + "`n"), [Text.UTF8Encoding]::new($false))
if (-not $KeepWorkFiles -and (Test-Path -LiteralPath $WorkDir) -and (Get-ChildItem -LiteralPath $WorkDir -Force).Count -eq 0) { Remove-Item -LiteralPath $WorkDir -Force }
Write-Host (($index | ConvertTo-Json -Depth 4))
