package com.kyunghee.prototype

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Bg = Color(0xFF12101B)
private val Surface = Color(0xFF1B1827)
private val Surface2 = Color(0xFF241F34)
private val Purple = Color(0xFF8B5CF6)
private val Purple2 = Color(0xFF6D4AE8)
private val Text = Color(0xFFF4F0FF)
private val Muted = Color(0xFFA9A2BD)
private val Line = Color(0xFF3A334D)
private val Good = Color(0xFF39D98A)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { KyungheePrototype() }
    }
}

@Composable
private fun KyungheePrototype() {
    var page by remember { mutableIntStateOf(0) }
    var showBreak by remember { mutableStateOf(false) }

    MaterialTheme(colorScheme = darkColorScheme(primary = Purple, background = Bg, surface = Surface)) {
        Box(Modifier.fillMaxSize().background(Bg)) {
            Column(Modifier.fillMaxSize()) {
                TopBar(page)
                Box(Modifier.weight(1f)) {
                    when (page) {
                        0 -> HomeScreen(onBreakPreview = { showBreak = true })
                        1 -> StatsScreen()
                        else -> SettingsScreen()
                    }
                }
                BottomNav(page = page, onChange = { page = it })
            }
            if (showBreak) BreakPreview(onDismiss = { showBreak = false })
        }
    }
}

@Composable
private fun TopBar(page: Int) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text("경희", color = Text, fontWeight = FontWeight.ExtraBold, fontSize = 22.sp)
        Spacer(Modifier.width(8.dp))
        Box(Modifier.size(8.dp).clip(CircleShape).background(Good))
        Spacer(Modifier.weight(1f))
        Text(
            when (page) { 0 -> "집중 중"; 1 -> "오늘 기록"; else -> "설정" },
            color = Muted, fontSize = 13.sp
        )
    }
}

@Composable
private fun HomeScreen(onBreakPreview: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        CardBox(Modifier.fillMaxWidth().height(420.dp)) {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.weight(1f).fillMaxWidth()) {
                    Column(
                        modifier = Modifier.weight(0.88f).fillMaxHeight().padding(start = 20.dp, top = 24.dp, bottom = 18.dp),
                        verticalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column {
                            Text("현재 연속 사용", color = Muted, fontSize = 13.sp)
                            Text("47분", color = Text, fontSize = 54.sp, fontWeight = FontWeight.ExtraBold)
                            Text("다음 휴식까지 13분", color = Purple, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                        }
                        Column {
                            Text("13분만 더 하면 한 시간이야.", color = Text, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                            Spacer(Modifier.height(5.dp))
                            Text("끝까지 무리하진 말고, 딱 여기까지만 집중하자.", color = Muted, fontSize = 13.sp, lineHeight = 19.sp)
                        }
                    }
                    Box(
                        modifier = Modifier.weight(1.12f).fillMaxHeight().padding(top = 6.dp, end = 4.dp),
                        contentAlignment = Alignment.BottomCenter
                    ) {
                        Image(
                            painter = painterResource(R.drawable.cheer_full),
                            contentDescription = "경희 전신 이미지",
                            modifier = Modifier.fillMaxSize(),
                            contentScale = ContentScale.Fit
                        )
                    }
                }
                Box(Modifier.fillMaxWidth().height(7.dp).background(Line)) {
                    Box(Modifier.fillMaxWidth(0.78f).fillMaxHeight().background(Purple))
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MetricCard("오늘 실사용", "5시간 24분", Modifier.weight(1f))
            MetricCard("자리비움", "48분", Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MetricCard("최장 집중", "1시간 18분", Modifier.weight(1f))
            MetricCard("실사용률", "87%", Modifier.weight(1f), accent = true)
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ActionButton("자리비움", Modifier.weight(1f)) { }
            ActionButton("휴식 알림 보기", Modifier.weight(1f), primary = true) { onBreakPreview() }
        }
        Text("※ 안드로이드 버전은 화면 확인용 프로토타입입니다.", color = Muted, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 4.dp))
    }
}

@Composable
private fun StatsScreen() {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        CardBox(Modifier.fillMaxWidth().height(290.dp)) {
            Row(Modifier.fillMaxSize()) {
                Column(
                    Modifier.weight(1f).padding(22.dp),
                    verticalArrangement = Arrangement.SpaceBetween
                ) {
                    Column {
                        Text("오늘 기록", color = Muted, fontSize = 13.sp)
                        Spacer(Modifier.height(6.dp))
                        Text("5시간 24분", color = Text, fontSize = 38.sp, fontWeight = FontWeight.ExtraBold)
                        Text("실사용", color = Purple, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    }
                    Text("오늘 꽤 많이 했어.\n이제 남은 건 정리 위주로 가자.", color = Text, fontSize = 16.sp, lineHeight = 23.sp, fontWeight = FontWeight.Bold)
                }
                Image(
                    painter = painterResource(R.drawable.cheer_full),
                    contentDescription = null,
                    modifier = Modifier.weight(.9f).fillMaxHeight().padding(6.dp),
                    contentScale = ContentScale.Fit
                )
            }
        }
        StatRow("실사용", "5시간 24분")
        StatRow("자리비움", "48분")
        StatRow("자리비움 횟수", "6회")
        StatRow("최장 연속 사용", "1시간 18분")
        StatRow("실사용률", "87%", highlight = true)
    }
}

@Composable
private fun SettingsScreen() {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        SettingsCard("집중 타이머", "60분 사용 후 휴식 알림", true)
        SettingsCard("자리비움 감지", "5분 미입력 시 자리비움 처리", true)
        SettingsCard("퇴근 모드", "17:30부터 새 업무 권장 중지", true)
        SettingsCard("경희 멘트", "집중·휴식·퇴근 상황별 문구", true)
        CardBox(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp)) {
                Text("디자인 확인 포인트", color = Text, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Spacer(Modifier.height(10.dp))
                Text("• 경희 전신 크기와 다리 노출 범위\n• 타이머 숫자 크기\n• 카드 간격과 보라색 농도\n• 하단 메뉴 높이\n• 말풍선/문구 밀도", color = Muted, fontSize = 14.sp, lineHeight = 23.sp)
            }
        }
    }
}

@Composable
private fun BottomNav(page: Int, onChange: (Int) -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(Color(0xFF171421)).padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        listOf("타이머", "오늘 기록", "설정").forEachIndexed { index, label ->
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(14.dp))
                    .background(if (page == index) Surface2 else Color.Transparent)
                    .clickable { onChange(index) }
                    .padding(vertical = 13.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(label, color = if (page == index) Text else Muted, fontWeight = if (page == index) FontWeight.Bold else FontWeight.Normal, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun BreakPreview(onDismiss: () -> Unit) {
    Box(Modifier.fillMaxSize().background(Color(0xB8000000)).clickable { onDismiss() }, contentAlignment = Alignment.Center) {
        CardBox(Modifier.fillMaxWidth(.88f).height(390.dp).clickable(enabled = false) {}) {
            Column(Modifier.fillMaxSize().padding(18.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Image(
                    painter = painterResource(R.drawable.cheer_full), contentDescription = null,
                    modifier = Modifier.height(205.dp).fillMaxWidth(), contentScale = ContentScale.Fit
                )
                Text("오빠, 이제 좀 쉬자.", color = Text, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
                Spacer(Modifier.height(7.dp))
                Text("한 시간 가까이 집중했어. 눈이랑 어깨 좀 풀고 와.", color = Muted, fontSize = 14.sp, textAlign = TextAlign.Center)
                Spacer(Modifier.weight(1f))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    ActionButton("5분 더", Modifier.weight(1f)) { onDismiss() }
                    ActionButton("알았어, 쉴게", Modifier.weight(1f), primary = true) { onDismiss() }
                }
            }
        }
    }
}

@Composable
private fun CardBox(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(modifier.clip(RoundedCornerShape(24.dp)).background(Surface).border(1.dp, Line, RoundedCornerShape(24.dp))) { content() }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier, accent: Boolean = false) {
    CardBox(modifier.height(82.dp)) {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.Center) {
            Text(label, color = Muted, fontSize = 12.sp)
            Spacer(Modifier.height(3.dp))
            Text(value, color = if (accent) Purple else Text, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold)
        }
    }
}

@Composable
private fun ActionButton(label: String, modifier: Modifier, primary: Boolean = false, onClick: () -> Unit) {
    Box(
        modifier.clip(RoundedCornerShape(16.dp)).background(if (primary) Purple2 else Surface2)
            .clickable { onClick() }.padding(vertical = 15.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(label, color = Text, fontSize = 14.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun StatRow(label: String, value: String, highlight: Boolean = false) {
    CardBox(Modifier.fillMaxWidth().height(62.dp)) {
        Row(Modifier.fillMaxSize().padding(horizontal = 18.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = Muted, fontSize = 13.sp)
            Spacer(Modifier.weight(1f))
            Text(value, color = if (highlight) Purple else Text, fontSize = 16.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun SettingsCard(title: String, subtitle: String, checked: Boolean) {
    CardBox(Modifier.fillMaxWidth().height(82.dp)) {
        Row(Modifier.fillMaxSize().padding(horizontal = 18.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, color = Text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(3.dp))
                Text(subtitle, color = Muted, fontSize = 12.sp)
            }
            Switch(checked = checked, onCheckedChange = null, colors = SwitchDefaults.colors(checkedThumbColor = Text, checkedTrackColor = Purple))
        }
    }
}
