#pragma once
#include "SSD1306Wire.h"

class SimpleMenu {
public:
  struct Item { const char* label; };

  SimpleMenu(SSD1306Wire* display, const Item* items, int count)
    : display_(display), items_(items), count_(count), cursor_(0) {
    draw();
  }

  void scroll(int delta) {
    cursor_ = (cursor_ + delta + count_) % count_;
    draw();
  }

  int cursor() const { return cursor_; }

  void draw() const {
    display_->clear();
    display_->setFont(ArialMT_Plain_16);
    display_->drawString(0, 0, "Settings");
    display_->drawHorizontalLine(0, 18, 128);
    for (int i = 0; i < count_; i++) {
      int y = 22 + i * 14;
      if (i == cursor_) {
        display_->fillRect(0, y - 1, 128, 13);
        display_->setColor(BLACK);
      }
      display_->setFont(ArialMT_Plain_10);
      display_->drawString(4, y, items_[i].label);
      display_->setColor(WHITE);
    }
    display_->display();
  }

private:
  SSD1306Wire* display_;
  const Item* items_;
  int count_;
  int cursor_;
};
