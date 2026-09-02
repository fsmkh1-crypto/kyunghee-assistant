package com.kyunghee.prototype

import android.app.Activity
import android.app.AlertDialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.*

class MainActivity : Activity() {
    private val bg = Color.rgb(18, 16, 27)
    private val panel = Color.rgb(27, 24, 39)
    private val panel2 = Color.rgb(36, 31, 52)
    private val purple = Color.rgb(139, 92, 246)
    private val purple2 = Color.rgb(109, 74, 232)
    private val text = Color.rgb(244, 240, 255)
    private val muted = Color.rgb(169, 162, 189)
    private val good = Color.rgb(57, 217, 138)
    private val line = Color.rgb(58, 51, 77)

    private lateinit var body: FrameLayout
    private lateinit var statusText: TextView
    private var page = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        showApp()
    }

    private fun showApp() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bg)
        }
        root.addView(topBar())

        body = FrameLayout(this)
        root.addView(body, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
        ))
        root.addView(bottomNav())
        setContentView(root)
        showPage(0)
    }

    private fun topBar(): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(20), dp(12), dp(20), dp(10))
        }
        row.addView(label("경희", 22, text, true))
        row.addView(space(8))
        row.addView(View(this).apply { background = rounded(good, 999f) }, LinearLayout.LayoutParams(dp(8), dp(8)))
        row.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f))
        statusText = label("집중 중", 13, muted, false)
        row.addView(statusText)
        return row
    }

    private fun bottomNav(): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(10), dp(8), dp(10), dp(10))
            setBackgroundColor(Color.rgb(23, 20, 33))
        }
        listOf("타이머", "오늘 기록", "설정").forEachIndexed { index, title ->
            val button = TextView(this).apply {
                text = title
                gravity = Gravity.CENTER
                setTextColor(text)
                textSize = 13f
                setPadding(0, dp(13), 0, dp(13))
                background = rounded(panel2, 14f)
                setOnClickListener { showPage(index) }
            }
            val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            lp.setMargins(dp(4), 0, dp(4), 0)
            row.addView(button, lp)
        }
        return row
    }

    private fun showPage(index: Int) {
        page = index
        statusText.text = when (index) { 0 -> "집중 중"; 1 -> "오늘 기록"; else -> "설정" }
        body.removeAllViews()
        val content = when (index) { 0 -> home(); 1 -> stats(); else -> settings() }
        body.addView(content)
    }

    private fun home(): View {
        val scroll = ScrollView(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(2), dp(16), dp(18))
        }

        val hero = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = cardBg()
            setPadding(dp(18), dp(18), dp(10), dp(12))
        }
        val words = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
        }
        words.addView(label("현재 연속 사용", 13, muted, false))
        words.addView(label("47분", 52, text, true))
        words.addView(label("다음 휴식까지 13분", 15, purple, true))
        words.addView(space(24))
        words.addView(label("13분만 더 하면 한 시간이야.", 18, text, true))
        words.addView(label("끝까지 무리하진 말고, 딱 여기까지만 집중하자.", 13, muted, false))
        hero.addView(words, LinearLayout.LayoutParams(0, dp(350), 1f))

        val image = ImageView(this).apply {
            setImageResource(R.drawable.cheer_full)
            scaleType = ImageView.ScaleType.FIT_CENTER
            adjustViewBounds = true
        }
        hero.addView(image, LinearLayout.LayoutParams(0, dp(350), 1f))
        col.addView(hero, fullWrapMargins(0, 0, 0, 12))

        val progress = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(line)
        }
        progress.addView(View(this).apply { setBackgroundColor(purple) }, LinearLayout.LayoutParams(0, dp(7), .78f))
        progress.addView(View(this), LinearLayout.LayoutParams(0, dp(7), .22f))
        col.addView(progress, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(7)))
        col.addView(space(12))

        col.addView(metricRow("오늘 실사용", "5시간 24분", "자리비움", "48분"))
        col.addView(space(10))
        col.addView(metricRow("최장 집중", "1시간 18분", "실사용률", "87%", true))
        col.addView(space(12))

        val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        actions.addView(action("자리비움", false) {}, LinearLayout.LayoutParams(0, dp(52), 1f).apply { marginEnd = dp(5) })
        actions.addView(action("휴식 알림 보기", true) { showBreak() }, LinearLayout.LayoutParams(0, dp(52), 1f).apply { marginStart = dp(5) })
        col.addView(actions)
        col.addView(space(10))
        col.addView(label("※ 안드로이드 버전은 화면 확인용 프로토타입입니다.", 11, muted, false))

        scroll.addView(col)
        return scroll
    }

    private fun stats(): View {
        val scroll = ScrollView(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(2), dp(16), dp(18))
        }
        val hero = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = cardBg()
            setPadding(dp(20), dp(16), dp(8), dp(12))
        }
        val left = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_VERTICAL }
        left.addView(label("오늘 기록", 13, muted, false))
        left.addView(label("5시간 24분", 36, text, true))
        left.addView(label("실사용", 14, purple, true))
        left.addView(space(22))
        left.addView(label("오늘 꽤 많이 했어.\n이제 남은 건 정리 위주로 가자.", 16, text, true))
        hero.addView(left, LinearLayout.LayoutParams(0, dp(260), 1.1f))
        hero.addView(ImageView(this).apply {
            setImageResource(R.drawable.cheer_full)
            scaleType = ImageView.ScaleType.FIT_CENTER
        }, LinearLayout.LayoutParams(0, dp(260), .9f))
        col.addView(hero, fullWrapMargins(0, 0, 0, 12))
        listOf(
            "실사용" to "5시간 24분",
            "자리비움" to "48분",
            "자리비움 횟수" to "6회",
            "최장 연속 사용" to "1시간 18분",
            "실사용률" to "87%"
        ).forEachIndexed { i, item ->
            col.addView(statRow(item.first, item.second, i == 4))
            col.addView(space(8))
        }
        scroll.addView(col)
        return scroll
    }

    private fun settings(): View {
        val scroll = ScrollView(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(2), dp(16), dp(18))
        }
        listOf(
            Triple("집중 타이머", "60분 사용 후 휴식 알림", true),
            Triple("자리비움 감지", "5분 미입력 시 자리비움 처리", true),
            Triple("퇴근 모드", "17:30부터 새 업무 권장 중지", true),
            Triple("경희 멘트", "집중·휴식·퇴근 상황별 문구", true)
        ).forEach { (a,b,c) ->
            col.addView(settingRow(a,b,c)); col.addView(space(10))
        }
        val info = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; background = cardBg(); setPadding(dp(18),dp(18),dp(18),dp(18)) }
        info.addView(label("디자인 확인 포인트", 16, text, true))
        info.addView(space(8))
        info.addView(label("• 경희 전신 크기와 다리 노출 범위\n• 타이머 숫자 크기\n• 카드 간격과 보라색 농도\n• 하단 메뉴 높이\n• 말풍선/문구 밀도", 14, muted, false))
        col.addView(info)
        scroll.addView(col)
        return scroll
    }

    private fun showBreak() {
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(18), dp(12), dp(18), dp(8))
        }
        content.addView(ImageView(this).apply {
            setImageResource(R.drawable.cheer_full)
            scaleType = ImageView.ScaleType.FIT_CENTER
        }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(190)))
        content.addView(label("오빠, 이제 좀 쉬자.", 22, Color.BLACK, true).apply { gravity = Gravity.CENTER })
        content.addView(space(6))
        content.addView(label("한 시간 가까이 집중했어. 눈이랑 어깨 좀 풀고 와.", 14, Color.DKGRAY, false).apply { gravity = Gravity.CENTER })
        AlertDialog.Builder(this)
            .setView(content)
            .setNegativeButton("5분 더", null)
            .setPositiveButton("알았어, 쉴게", null)
            .show()
    }

    private fun metricRow(a: String, av: String, b: String, bv: String, accentB: Boolean = false): View {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(metric(a, av, false), LinearLayout.LayoutParams(0, dp(82), 1f).apply { marginEnd = dp(5) })
        row.addView(metric(b, bv, accentB), LinearLayout.LayoutParams(0, dp(82), 1f).apply { marginStart = dp(5) })
        return row
    }

    private fun metric(title: String, value: String, accent: Boolean): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_VERTICAL
        background = cardBg()
        setPadding(dp(15), 0, dp(15), 0)
        addView(label(title, 12, muted, false))
        addView(label(value, 20, if (accent) purple else text, true))
    }

    private fun statRow(title: String, value: String, accent: Boolean): View = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = cardBg()
        setPadding(dp(18), 0, dp(18), 0)
        addView(label(title, 13, muted, false))
        addView(View(this@MainActivity), LinearLayout.LayoutParams(0, 1, 1f))
        addView(label(value, 16, if (accent) purple else text, true))
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(62))
    }

    private fun settingRow(title: String, subtitle: String, checked: Boolean): View = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = cardBg()
        setPadding(dp(18), 0, dp(14), 0)
        val words = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        words.addView(label(title, 15, text, true))
        words.addView(label(subtitle, 12, muted, false))
        addView(words, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        addView(Switch(this@MainActivity).apply { isChecked = checked; isEnabled = false })
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(82))
    }

    private fun action(title: String, primary: Boolean, click: () -> Unit): View = TextView(this).apply {
        text = title
        gravity = Gravity.CENTER
        textSize = 14f
        setTextColor(text)
        setTypeface(typeface, Typeface.BOLD)
        background = rounded(if (primary) purple2 else panel2, 16f)
        setOnClickListener { click() }
    }

    private fun label(value: String, sp: Int, color: Int, bold: Boolean): TextView = TextView(this).apply {
        text = value
        textSize = sp.toFloat()
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        includeFontPadding = false
        setLineSpacing(dp(2).toFloat(), 1f)
    }

    private fun cardBg() = rounded(panel, 24f, line)

    private fun rounded(fill: Int, radiusDp: Float, stroke: Int? = null) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = dp(radiusDp.toInt()).toFloat()
        setColor(fill)
        if (stroke != null) setStroke(dp(1), stroke)
    }

    private fun space(height: Int) = Space(this).apply { layoutParams = LinearLayout.LayoutParams(1, dp(height)) }
    private fun dp(v: Int): Int = (v * resources.displayMetrics.density + .5f).toInt()
    private fun fullWrapMargins(l: Int, t: Int, r: Int, b: Int) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { setMargins(dp(l), dp(t), dp(r), dp(b)) }
}
