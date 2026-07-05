import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'features/home/home_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: MobpcApp()));
}

class MobpcApp extends StatelessWidget {
  const MobpcApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'mobpc',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}
