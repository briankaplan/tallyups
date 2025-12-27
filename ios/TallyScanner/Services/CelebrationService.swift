import SwiftUI
import UIKit

// MARK: - Celebration Service

/// Service for triggering celebratory animations and micro-interactions
@MainActor
class CelebrationService: ObservableObject {
    static let shared = CelebrationService()

    @Published var showConfetti = false
    @Published var showCheckmark = false
    @Published var showStreak = false
    @Published var currentStreak = 0
    @Published var showMilestone = false
    @Published var milestoneText = ""

    private init() {}

    // MARK: - Celebration Triggers

    /// Celebrate a successful receipt match
    func celebrateMatch(merchant: String) {
        HapticService.shared.matchSuccess()

        // Show checkmark animation
        withAnimation(.spring(response: 0.4, dampingFraction: 0.6)) {
            showCheckmark = true
        }

        // Auto-dismiss
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            withAnimation(.easeOut(duration: 0.3)) {
                self.showCheckmark = false
            }
        }

        // Check for streak
        updateStreak()
    }

    /// Celebrate completing all pending receipts
    func celebrateInboxClear() {
        HapticService.shared.notification(.success)
        triggerConfetti()

        milestoneText = "Inbox Clear!"
        withAnimation(.spring()) {
            showMilestone = true
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            withAnimation {
                self.showMilestone = false
            }
        }
    }

    /// Celebrate a streak milestone
    func celebrateStreak(_ count: Int) {
        currentStreak = count
        HapticService.shared.notification(.success)

        withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) {
            showStreak = true
        }

        if count >= 10 {
            triggerConfetti()
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            withAnimation {
                self.showStreak = false
            }
        }
    }

    /// Celebrate reaching a receipt count milestone
    func celebrateMilestone(count: Int) {
        let milestones = [10, 25, 50, 100, 250, 500, 1000]

        if milestones.contains(count) {
            triggerConfetti()
            HapticService.shared.notification(.success)

            milestoneText = "\(count) Receipts!"
            withAnimation(.spring()) {
                showMilestone = true
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                withAnimation {
                    self.showMilestone = false
                }
            }
        }
    }

    /// Trigger confetti explosion
    func triggerConfetti() {
        withAnimation {
            showConfetti = true
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            withAnimation {
                self.showConfetti = false
            }
        }
    }

    // MARK: - Private

    private func updateStreak() {
        // Update streak counter (would be persisted in reality)
        currentStreak += 1

        if currentStreak % 5 == 0 {
            celebrateStreak(currentStreak)
        }
    }
}

// MARK: - Confetti View

struct ConfettiView: View {
    @State private var particles: [ConfettiParticle] = []

    var body: some View {
        ZStack {
            ForEach(particles) { particle in
                ConfettiParticleView(particle: particle)
            }
        }
        .allowsHitTesting(false)
        .onAppear {
            generateParticles()
        }
    }

    private func generateParticles() {
        particles = (0..<50).map { _ in
            ConfettiParticle(
                color: [.red, .blue, .green, .yellow, .purple, .orange, .pink].randomElement()!,
                x: CGFloat.random(in: 0...UIScreen.main.bounds.width),
                y: -20,
                rotation: Double.random(in: 0...360),
                scale: CGFloat.random(in: 0.5...1.5)
            )
        }
    }
}

struct ConfettiParticle: Identifiable {
    let id = UUID()
    let color: Color
    let x: CGFloat
    let y: CGFloat
    let rotation: Double
    let scale: CGFloat
}

struct ConfettiParticleView: View {
    let particle: ConfettiParticle
    @State private var yOffset: CGFloat = 0
    @State private var xOffset: CGFloat = 0
    @State private var rotation: Double = 0
    @State private var opacity: Double = 1

    var body: some View {
        Rectangle()
            .fill(particle.color)
            .frame(width: 8 * particle.scale, height: 16 * particle.scale)
            .rotationEffect(.degrees(rotation))
            .position(x: particle.x + xOffset, y: particle.y + yOffset)
            .opacity(opacity)
            .onAppear {
                withAnimation(.easeOut(duration: 3).delay(Double.random(in: 0...0.5))) {
                    yOffset = UIScreen.main.bounds.height + 100
                    xOffset = CGFloat.random(in: -100...100)
                    rotation = particle.rotation + Double.random(in: 360...720)
                    opacity = 0
                }
            }
    }
}

// MARK: - Success Checkmark View

struct SuccessCheckmarkView: View {
    @State private var drawProgress: CGFloat = 0
    @State private var circleScale: CGFloat = 0.5
    @State private var opacity: Double = 0

    var body: some View {
        ZStack {
            // Background circle
            Circle()
                .fill(Color.tallyAccent)
                .frame(width: 120, height: 120)
                .scaleEffect(circleScale)

            // Checkmark
            CheckmarkShape()
                .trim(from: 0, to: drawProgress)
                .stroke(Color.black, style: StrokeStyle(lineWidth: 6, lineCap: .round, lineJoin: .round))
                .frame(width: 50, height: 50)
        }
        .opacity(opacity)
        .onAppear {
            // Circle animation
            withAnimation(.spring(response: 0.4, dampingFraction: 0.6)) {
                circleScale = 1.0
                opacity = 1.0
            }

            // Checkmark draw animation
            withAnimation(.easeOut(duration: 0.3).delay(0.2)) {
                drawProgress = 1.0
            }
        }
    }
}

struct CheckmarkShape: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let start = CGPoint(x: rect.minX, y: rect.midY)
        let middle = CGPoint(x: rect.midX - 5, y: rect.maxY - 10)
        let end = CGPoint(x: rect.maxX, y: rect.minY + 5)

        path.move(to: start)
        path.addLine(to: middle)
        path.addLine(to: end)

        return path
    }
}

// MARK: - Streak Badge View

struct StreakBadgeView: View {
    let count: Int
    @State private var scale: CGFloat = 0.5
    @State private var rotation: Double = -30

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                // Fire glow
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [.orange.opacity(0.6), .clear],
                            center: .center,
                            startRadius: 0,
                            endRadius: 60
                        )
                    )
                    .frame(width: 120, height: 120)
                    .blur(radius: 10)

                // Fire emoji
                Text("🔥")
                    .font(.system(size: 64))
            }

            Text("\(count) in a row!")
                .font(.title2.bold())
                .foregroundColor(.white)
        }
        .scaleEffect(scale)
        .rotationEffect(.degrees(rotation))
        .onAppear {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) {
                scale = 1.0
                rotation = 0
            }
        }
    }
}

// MARK: - Milestone Banner View

struct MilestoneBannerView: View {
    let text: String
    @State private var offset: CGFloat = -200
    @State private var opacity: Double = 0

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "trophy.fill")
                .font(.title2)
                .foregroundColor(.yellow)

            Text(text)
                .font(.headline)
                .foregroundColor(.white)

            Image(systemName: "trophy.fill")
                .font(.title2)
                .foregroundColor(.yellow)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
        .background(
            Capsule()
                .fill(
                    LinearGradient(
                        colors: [.purple, .blue],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .shadow(color: .purple.opacity(0.5), radius: 20, y: 5)
        )
        .offset(y: offset)
        .opacity(opacity)
        .onAppear {
            withAnimation(.spring(response: 0.6, dampingFraction: 0.7)) {
                offset = 0
                opacity = 1
            }
        }
    }
}

// MARK: - Celebration Overlay Modifier

struct CelebrationOverlay: ViewModifier {
    @ObservedObject var service = CelebrationService.shared

    func body(content: Content) -> some View {
        content
            .overlay {
                ZStack {
                    // Confetti
                    if service.showConfetti {
                        ConfettiView()
                            .transition(.opacity)
                    }

                    // Checkmark
                    if service.showCheckmark {
                        Color.black.opacity(0.4)
                            .ignoresSafeArea()
                        SuccessCheckmarkView()
                            .transition(.scale.combined(with: .opacity))
                    }

                    // Streak
                    if service.showStreak {
                        Color.black.opacity(0.4)
                            .ignoresSafeArea()
                        StreakBadgeView(count: service.currentStreak)
                            .transition(.scale.combined(with: .opacity))
                    }

                    // Milestone banner
                    if service.showMilestone {
                        VStack {
                            MilestoneBannerView(text: service.milestoneText)
                            Spacer()
                        }
                        .padding(.top, 100)
                    }
                }
                .animation(.spring(), value: service.showConfetti)
                .animation(.spring(), value: service.showCheckmark)
                .animation(.spring(), value: service.showStreak)
                .animation(.spring(), value: service.showMilestone)
            }
    }
}

extension View {
    func withCelebrations() -> some View {
        modifier(CelebrationOverlay())
    }
}

// MARK: - Animated Counter View

struct AnimatedCounterView: View {
    let value: Int
    let font: Font
    let color: Color

    @State private var displayedValue: Int = 0

    var body: some View {
        Text("\(displayedValue)")
            .font(font)
            .foregroundColor(color)
            .contentTransition(.numericText())
            .onChange(of: value) { _, newValue in
                withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                    displayedValue = newValue
                }
            }
            .onAppear {
                displayedValue = value
            }
    }
}

// MARK: - Shimmer Effect

struct ShimmerModifier: ViewModifier {
    @State private var phase: CGFloat = 0

    func body(content: Content) -> some View {
        content
            .overlay {
                GeometryReader { geo in
                    LinearGradient(
                        colors: [
                            .clear,
                            .white.opacity(0.3),
                            .clear
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                    .frame(width: geo.size.width * 2)
                    .offset(x: -geo.size.width + phase * geo.size.width * 2)
                }
                .mask(content)
            }
            .onAppear {
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                    phase = 1
                }
            }
    }
}

extension View {
    func shimmer() -> some View {
        modifier(ShimmerModifier())
    }
}

// MARK: - Bounce Effect

struct BounceModifier: ViewModifier {
    let isActive: Bool
    @State private var scale: CGFloat = 1

    func body(content: Content) -> some View {
        content
            .scaleEffect(scale)
            .onChange(of: isActive) { _, newValue in
                if newValue {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.5)) {
                        scale = 1.1
                    }
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.5).delay(0.15)) {
                        scale = 1.0
                    }
                }
            }
    }
}

extension View {
    func bounce(when condition: Bool) -> some View {
        modifier(BounceModifier(isActive: condition))
    }
}

// MARK: - Glow Effect

struct GlowModifier: ViewModifier {
    let color: Color
    let radius: CGFloat
    @State private var opacity: Double = 0.5

    func body(content: Content) -> some View {
        content
            .shadow(color: color.opacity(opacity), radius: radius)
            .onAppear {
                withAnimation(.easeInOut(duration: 1).repeatForever(autoreverses: true)) {
                    opacity = 1
                }
            }
    }
}

extension View {
    func glow(color: Color = .tallyAccent, radius: CGFloat = 10) -> some View {
        modifier(GlowModifier(color: color, radius: radius))
    }
}
