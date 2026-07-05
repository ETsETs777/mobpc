import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';

class KeyboardScreen extends ConsumerStatefulWidget {
  const KeyboardScreen({super.key});

  @override
  ConsumerState<KeyboardScreen> createState() => _KeyboardScreenState();
}

class _KeyboardScreenState extends ConsumerState<KeyboardScreen> {
  final _textCtrl = TextEditingController();

  Future<void> _type() async {
    final text = _textCtrl.text;
    if (text.isEmpty) return;
    final client = ref.read(mobpcClientProvider);
    await client.send('keyboard.type', payload: {'text': text});
    _textCtrl.clear();
  }

  Future<void> _hotkey(List<String> keys) async {
    final client = ref.read(mobpcClientProvider);
    await client.send('keyboard.hotkey', payload: {'keys': keys});
  }

  @override
  void dispose() {
    _textCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Клавиатура')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _textCtrl,
              decoration: const InputDecoration(
                labelText: 'Текст для ввода',
                border: OutlineInputBorder(),
              ),
              onSubmitted: (_) => _type(),
            ),
            const SizedBox(height: 8),
            FilledButton(onPressed: _type, child: const Text('Отправить')),
            const SizedBox(height: 24),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _HotkeyButton('Ctrl+C', () => _hotkey(['ctrl', 'c'])),
                _HotkeyButton('Ctrl+V', () => _hotkey(['ctrl', 'v'])),
                _HotkeyButton('Alt+Tab', () => _hotkey(['alt', 'tab'])),
                _HotkeyButton('Win', () => _hotkey(['win'])),
                _HotkeyButton('Enter', () => _hotkey(['enter'])),
                _HotkeyButton('Esc', () => _hotkey(['esc'])),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _HotkeyButton extends StatelessWidget {
  const _HotkeyButton(this.label, this.onPressed);

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(onPressed: onPressed, child: Text(label));
  }
}
