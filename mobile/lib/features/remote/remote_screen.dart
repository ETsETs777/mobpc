import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';
import '../keyboard/keyboard_screen.dart';
import '../quick_actions/quick_actions_screen.dart';
import '../terminal/terminal_screen.dart';
import '../files/files_screen.dart';

class RemoteScreen extends ConsumerStatefulWidget {
  const RemoteScreen({super.key});

  @override
  ConsumerState<RemoteScreen> createState() => _RemoteScreenState();
}

class _RemoteScreenState extends ConsumerState<RemoteScreen> {
  Uint8List? _screenImage;
  int _screenW = 1920;
  int _screenH = 1080;
  bool _loading = false;
  Offset? _lastTouch;
  double _scale = 1.0;

  @override
  void initState() {
    super.initState();
    _refreshScreen();
  }

  Future<void> _refreshScreen() async {
    setState(() => _loading = true);
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send('screen.capture', payload: {'quality': 60});
      if (resp.ok && resp.data != null) {
        final b64 = resp.data!['image'] as String;
        setState(() {
          _screenImage = base64Decode(b64);
          _screenW = resp.data!['width'] as int? ?? _screenW;
          _screenH = resp.data!['height'] as int? ?? _screenH;
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _sendClick(Offset local, Size viewSize, String button) async {
    final x = (local.dx / viewSize.width * _screenW).round();
    final y = (local.dy / viewSize.height * _screenH).round();
    final client = ref.read(mobpcClientProvider);
    await client.send('mouse.click', payload: {
      'x': x,
      'y': y,
      'button': button,
    });
    _refreshScreen();
  }

  Future<void> _sendMove(Offset local, Size viewSize) async {
    final x = (local.dx / viewSize.width * _screenW).round();
    final y = (local.dy / viewSize.height * _screenH).round();
    if (_lastTouch != null &&
        (_lastTouch!.dx - local.dx).abs() < 3 &&
        (_lastTouch!.dy - local.dy).abs() < 3) {
      return;
    }
    _lastTouch = local;
    final client = ref.read(mobpcClientProvider);
    await client.send('mouse.move', payload: {'x': x, 'y': y});
  }

  Future<void> _sendScroll(double dy) async {
    final client = ref.read(mobpcClientProvider);
    await client.send('mouse.scroll', payload: {'dy': dy > 0 ? -3 : 3});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Удалённый рабочий стол'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _refreshScreen,
          ),
          PopupMenuButton<String>(
            onSelected: (v) {
              switch (v) {
                case 'keyboard':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const KeyboardScreen()));
                  break;
                case 'terminal':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const TerminalScreen()));
                  break;
                case 'files':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const FilesScreen()));
                  break;
                case 'actions':
                  Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const QuickActionsScreen()),
                  );
                  break;
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'keyboard', child: Text('Клавиатура')),
              PopupMenuItem(value: 'terminal', child: Text('Терминал')),
              PopupMenuItem(value: 'files', child: Text('Файлы')),
              PopupMenuItem(value: 'actions', child: Text('Быстрые действия')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final viewSize = Size(constraints.maxWidth, constraints.maxHeight);
                return GestureDetector(
                  onTapUp: (d) => _sendClick(d.localPosition, viewSize, 'left'),
                  onLongPress: () {
                    if (_lastTouch != null) {
                      _sendClick(_lastTouch!, viewSize, 'right');
                    }
                  },
                  onPanUpdate: (d) => _sendMove(d.localPosition, viewSize),
                  onScaleUpdate: (d) {
                    if (d.scale != 1.0) {
                      setState(() => _scale = (_scale * d.scale).clamp(0.5, 3.0));
                    }
                  },
                  child: InteractiveViewer(
                    scaleEnabled: true,
                    minScale: 0.5,
                    maxScale: 4,
                    child: _screenImage == null
                        ? const Center(child: CircularProgressIndicator())
                        : Image.memory(_screenImage!, fit: BoxFit.contain),
                  ),
                );
              },
            ),
          ),
          SizedBox(
            height: 120,
            child: GestureDetector(
              onPanUpdate: (d) => _sendMove(
                Offset(d.localPosition.dx, d.localPosition.dy),
                const Size(300, 120),
              ),
              onTapUp: (d) => _sendClick(
                d.localPosition,
                const Size(300, 120),
                'left',
              ),
              onLongPress: () {
                if (_lastTouch != null) {
                  _sendClick(_lastTouch!, const Size(300, 120), 'right');
                }
              },
              child: Container(
                margin: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.grey.shade800,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Center(
                  child: Text('Тачпад', style: TextStyle(color: Colors.white70)),
                ),
              ),
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(
                icon: const Icon(Icons.arrow_upward),
                onPressed: () => _sendScroll(-1),
              ),
              IconButton(
                icon: const Icon(Icons.arrow_downward),
                onPressed: () => _sendScroll(1),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
